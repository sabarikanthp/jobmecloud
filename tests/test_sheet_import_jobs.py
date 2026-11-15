import io
from datetime import date, datetime, timezone

import openpyxl
import pytest
from fakes import add_job
from sqlmodel import select

from jobmecloud.db.models import ActivityLog, CustomField, CustomValue, Job
from jobmecloud.importers import sheet_import
from jobmecloud.importers.sheet_import import ImportFailure, SheetImportIn, run_import
from jobmecloud.importers.tracker import Sheet
from jobmecloud.jobs import custom_fields as cf

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
COLUMNS = ["Employer", "Role", "Requisition", "Application Status", "Decision", "Applied Date",
           "Pay", "Location / Work Mode", "Link", "Notes", "Review date", "Confirmation"]


def row(employer="Northwind Labs", role="Data Engineer", req="", status="", decision="", applied="",
        pay="", loc="", link="", notes="", review="", confirm=""):
    return [employer, role, req, status, decision, applied, pay, loc, link, notes, review, confirm]


def body(sheet, **over):
    mapping = {"employer": "Employer", "title": "Role", "requisition": "Requisition",
               "status": "Application Status", "applied_date": "Applied Date",
               "pay": "Pay", "location": "Location / Work Mode", "url": "Link", "notes": "Notes"}
    data = {"upload_id": "u", "sheet": sheet.name, "kind": "jobs", "mapping": mapping}
    data.update(over)
    return SheetImportIn(**data)


def go(session, rows, **over):
    sheet = Sheet("Job Master", COLUMNS, rows)
    report = run_import(session, sheet, body(sheet, **over), now=NOW)
    session.commit()
    return report


def jobs(session):
    return list(session.exec(select(Job).order_by(Job.id)))


def test_new_jobs_are_created_with_mapped_fields_and_custom_values(session):
    report = go(session, [
        row(req="R-1", status="APPLIED", applied="2026-03-14", pay="$150,000 - $180,000",
            loc="Springfield, IL hybrid", link="https://example.com/jobs/1", notes="Great team",
            review="2026-03-20", confirm="Yes"),
        row("Contoso Health", "Analyst", status="SKIPPED", confirm="No"),
    ], keep={"Review date": {"new": {"name": "Review date", "type": "date"}},
             "Confirmation": {"new": {"name": "Confirmation", "type": "choice"}}})
    assert report["counts"] == {"new": 2, "updated": 0, "unchanged": 0, "left_out": 0}
    first, second = jobs(session)
    assert (first.employer, first.title, first.requisition_id, first.status) == (
        "Northwind Labs", "Data Engineer", "R-1", "Applied")
    assert (first.pay_min, first.pay_max) == (150000, 180000)
    assert (first.location, first.work_mode) == ("Springfield, IL", "Hybrid")
    assert first.apply_url == "https://example.com/jobs/1" and first.notes == "Great team"
    assert first.applied_at == datetime(2026, 3, 14, tzinfo=timezone.utc) or first.applied_at.date() == date(2026, 3, 14)
    assert first.origin == "import"
    assert (second.status, second.skip_reason, second.skip_note) == ("Skipped", "Other", "SKIPPED")
    fields = {f.name: f for f in cf.list_fields(session)}
    assert fields["Confirmation"].type == "choice" and fields["Confirmation"].choices == ["No", "Yes"]
    values = cf.values_for(session, [first.id, second.id])
    assert values[first.id][fields["Review date"].id] == "2026-03-20"
    assert values[first.id][fields["Confirmation"].id] == "Yes"
    assert values[second.id] == {fields["Confirmation"].id: "No"}
    actions = [r.action for r in session.exec(select(ActivityLog).where(ActivityLog.job_id == first.id))]
    assert "imported" in actions


def test_a_decision_column_does_not_change_the_status_and_can_be_kept(session):
    go(session, [row("Northwind Labs", "A", status="REVIEWED", decision="SKIPPED"),
                 row("Northwind Labs", "B", status="APPLIED", decision="NOT DECIDED")],
       keep={"Decision": {"new": {"name": "Decision", "type": "choice"}}})
    a, b = jobs(session)
    assert (a.status, b.status) == ("New", "Applied")
    field = cf.list_fields(session)[0]
    assert field.choices == ["NOT DECIDED", "SKIPPED"]
    assert cf.values_for(session, [a.id, b.id]) == {a.id: {field.id: "SKIPPED"}, b.id: {field.id: "NOT DECIDED"}}


def test_a_column_matched_to_a_jobme_field_can_also_be_kept(session):
    go(session, [row("Northwind Labs", "A", status="REVIEWED"), row("Northwind Labs", "B", status="HOLD"),
                 row("Northwind Labs", "C", status="REVIEWED")],
       keep={"Application Status": {"new": {"name": "Status in file", "type": "choice"}}})
    field = cf.list_fields(session)[0]
    assert field.name == "Status in file" and field.choices == ["HOLD", "REVIEWED"]
    values = cf.values_for(session, [j.id for j in jobs(session)])
    assert [values[j.id][field.id] for j in jobs(session)] == ["REVIEWED", "HOLD", "REVIEWED"]
    assert {j.status for j in jobs(session)} == {"New"}


def test_one_location_column_fills_location_and_work_mode_without_pollution(session):
    go(session, [row("Northwind Labs", "A", loc="Remote"), row("Northwind Labs", "B", loc="Portland, OR"),
                 row("Northwind Labs", "C", loc="Springfield, IL hybrid")])
    a, b, c = jobs(session)
    assert (a.location, a.work_mode) == (None, "Remote")
    assert (b.location, b.work_mode) == ("Portland, OR", None)
    assert (c.location, c.work_mode) == ("Springfield, IL", "Hybrid")


def test_reimport_repairs_a_work_mode_that_is_not_a_mode_and_keeps_real_ones(session):
    e = session.get_bind()
    bad = add_job(e, employer="Northwind Labs", title="A", location="Portland, OR", work_mode="Portland, OR")
    good = add_job(e, employer="Northwind Labs", title="B", work_mode="remote")
    typed = add_job(e, employer="Northwind Labs", title="C", work_mode="Hybrid")
    empty = add_job(e, employer="Northwind Labs", title="D")
    go(session, [row(role="A", loc="Portland, OR"), row(role="B", loc="Hybrid"), row(role="C", loc="Remote"),
                 row(role="D", loc="Springfield, IL hybrid")])
    assert session.get(Job, bad).work_mode is None
    assert session.get(Job, good).work_mode == "remote"
    assert session.get(Job, typed).work_mode == "Hybrid"
    assert (session.get(Job, empty).work_mode, session.get(Job, empty).location) == ("Hybrid", "Springfield, IL")


def test_status_words_mapping_overrides_the_default_and_words_are_listed(session):
    report = go(session, [row("Northwind Labs", "A", status="WEIRD"), row("Contoso Health", "B", status="WEIRD"),
                          row("Adatum", "C", status="Applied")],
                status_words={"weird": "Rejected"})
    assert [j.status for j in jobs(session)] == ["Rejected", "Rejected", "Applied"]
    words = {w["word"]: w for w in report["words"]}
    assert words["WEIRD"]["count"] == 2 and words["WEIRD"]["status"] == "Rejected"
    assert words["Applied"]["status"] == "Applied"


def test_dry_run_changes_nothing_but_reports_the_same_counts(session):
    sheet = Sheet("Job Master", COLUMNS, [row(status="Applied"), row("Contoso Health", "Analyst")])
    dry = run_import(session, sheet, body(sheet, dry_run=True), now=NOW)
    session.rollback()
    assert jobs(session) == []
    real = run_import(session, sheet, body(sheet), now=NOW)
    session.commit()
    assert dry["counts"] == real["counts"] == {"new": 2, "updated": 0, "unchanged": 0, "left_out": 0}
    assert len(jobs(session)) == 2


def test_reimport_changes_nothing(session):
    rows = [row(req="R-1", status="APPLIED", applied="2026-03-14", pay="$150,000 - $180,000",
                loc="Springfield, IL hybrid", notes="Great team", review="2026-03-20", confirm="Yes"),
            row("Contoso Health", "Analyst", status="REVIEWED", decision="SKIPPED", pay="negotiable")]
    keep = {"Review date": {"new": {"name": "Review date", "type": "date"}},
            "Confirmation": {"new": {"name": "Confirmation", "type": "choice"}}}
    go(session, rows, keep=keep)
    logs = len(session.exec(select(ActivityLog)).all())
    values = len(session.exec(select(CustomValue)).all())
    again = go(session, rows, keep=keep)
    assert again["counts"] == {"new": 0, "updated": 0, "unchanged": 2, "left_out": 0}
    assert len(jobs(session)) == 2
    assert len(session.exec(select(ActivityLog)).all()) == logs
    assert len(session.exec(select(CustomValue)).all()) == values
    assert len(cf.list_fields(session)) == 2
    assert jobs(session)[1].notes == "Pay in file: negotiable"


def test_ambiguous_match_is_left_out(session):
    add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer", location="Austin, TX")
    add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer", location="Boston, MA")
    report = go(session, [row(applied="2026-03-14")])
    assert report["counts"]["left_out"] == 1 and report["counts"]["new"] == 0
    assert report["attention"] == [{"row": 1, "reason": "More than one job matches."}]
    assert all(j.applied_at is None for j in jobs(session))


def test_existing_job_only_fills_empty_fields_and_never_overwrites(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer", location="Austin, TX",
                  notes="My own note", apply_url="https://mine.example/1")
    report = go(session, [row(req="R-9", loc="austin,  tx", link="https://other.example/2", notes="Their note",
                              pay="$100,000 - $120,000", applied="2026-03-14")])
    job = session.get(Job, jid)
    assert report["counts"]["updated"] == 1
    assert job.requisition_id == "R-9" and (job.pay_min, job.pay_max) == (100000, 120000)
    assert job.location == "Austin, TX" and job.apply_url == "https://mine.example/1"
    assert job.notes == "My own note"
    assert job.applied_at.date() == date(2026, 3, 14)


def test_status_moves_forward_only_and_skipped_is_untouched(session):
    e = session.get_bind()
    new = add_job(e, employer="Northwind Labs", title="A", status="New")
    applied = add_job(e, employer="Northwind Labs", title="B", status="Applied",
                      applied_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    rejected = add_job(e, employer="Northwind Labs", title="C", status="Rejected")
    skipped = add_job(e, employer="Northwind Labs", title="D", status="Skipped")
    report = go(session, [row(role="A", status="Applied", applied="2026-03-14"), row(role="B", status="Applied"),
                          row(role="C", status="Applied"), row(role="D", status="Applied")])
    assert report["attention"] == []  # leaving a job alone is quiet, not an error
    status = {j.title: j.status for j in jobs(session)}
    assert status == {"A": "Applied", "B": "Applied", "C": "Rejected", "D": "Skipped"}
    job = session.get(Job, new)
    assert job.applied_at.date() == date(2026, 3, 14)
    entries = session.exec(select(ActivityLog).where(ActivityLog.job_id == new,
                                                     ActivityLog.action == "status_changed")).all()
    assert [(r.from_value, r.to_value, r.actor) for r in entries] == [("New", "Applied", "user")]
    go(session, [row(role="B", status="Interview")])
    assert session.get(Job, applied).status == "Interviewing"
    assert session.get(Job, rejected).status == "Rejected" and session.get(Job, skipped).status == "Skipped"


def test_a_status_advance_never_invents_response_or_outcome_dates(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="A", status="Applied",
                  applied_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    go(session, [row(role="A", status="Interview")])
    job = session.get(Job, jid)
    assert job.status == "Interviewing"
    assert job.first_response_at is None and job.outcome_at is None
    assert job.applied_at.date() == date(2026, 3, 1)
    go(session, [row(role="A", status="Rejected")])
    job = session.get(Job, jid)
    assert job.status == "Rejected" and job.first_response_at is None and job.outcome_at is None


def test_a_sheets_response_date_is_used_when_the_status_advances(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="A", status="Applied",
                  applied_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    sheet = Sheet("Job Master", COLUMNS + ["Response"], [row(role="A", status="Interview") + ["2026-03-09"]])
    mapping = {**body(sheet).mapping, "first_response_date": "Response"}
    run_import(session, sheet, body(sheet, mapping=mapping), now=NOW)
    session.commit()
    job = session.get(Job, jid)
    assert job.status == "Interviewing" and job.first_response_at.date() == date(2026, 3, 9)


def test_progress_past_applied_steps_through_applied(session):
    e = session.get_bind()
    new = add_job(e, employer="Northwind Labs", title="A", status="New")
    ready = add_job(e, employer="Northwind Labs", title="B", status="Ready")
    go(session, [row(role="A", status="Interview", applied="2026-03-14"), row(role="B", status="Offer")])
    a, b = session.get(Job, new), session.get(Job, ready)
    assert (a.status, b.status) == ("Interviewing", "Offer")
    assert a.applied_at.date() == date(2026, 3, 14) and b.applied_at is not None
    steps = [(r.from_value, r.to_value) for r in session.exec(select(ActivityLog).where(
        ActivityLog.job_id == new, ActivityLog.action == "status_changed").order_by(ActivityLog.id))]
    assert steps == [("New", "Applied"), ("Applied", "Interviewing")]
    assert a.first_response_at is None and b.outcome_at is None


def test_future_dates_are_not_stored_and_do_not_half_update_a_job(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="A", status="New")
    go(session, [row(role="A", status="Applied", applied="2099-01-01"),
                 row("Contoso Health", "B", status="Applied", applied="2099-01-01")])
    a = session.get(Job, jid)
    assert a.applied_at is not None and a.applied_at.year < 2099  # the status step used today
    assert "Applied date in file: 2099-01-01" in a.notes
    b = [j for j in jobs(session) if j.employer == "Contoso Health"][0]
    assert b.applied_at is None and b.first_seen_at.year < 2099
    assert "Applied date in file: 2099-01-01" in b.notes


def test_the_message_and_sample_use_the_right_words_for_contacts(session):
    from jobmecloud.importers.sheet_import import SheetImportIn as In
    sheet = Sheet("Contacts", ["Contact", "Employer"], [["Sam Example", "Northwind Labs"]])
    report = run_import(session, sheet, In(upload_id="u", sheet="Contacts", kind="contacts",
                                           mapping={"name": "Contact", "employer": "Employer"}), now=NOW)
    assert report["message"] == "Imported 1 new contact, updated 0, 0 already in JobMe, 0 left out."
    assert report["sample"][0]["status"] == ""


def test_unreadable_date_and_number_cells_are_left_empty_and_noted(session):
    report = go(session, [row(applied="sometime in spring", review="soon", confirm="")],
                keep={"Review date": {"new": {"name": "Review date", "type": "date"}}})
    assert report["counts"]["new"] == 1
    job = jobs(session)[0]
    assert job.applied_at is None
    assert "Applied date in file: sometime in spring" in job.notes
    assert "Review date in file: soon" in job.notes
    assert session.exec(select(CustomValue)).all() == []


def test_a_value_outside_an_existing_choice_field_is_flagged_and_left_empty(session):
    field = cf.create_field(session, name="Decision", type="choice", choices=["Yes", "No"], at=NOW)
    session.commit()
    report = go(session, [row(confirm="Maybe")], keep={"Confirmation": {"field_id": field.id}})
    assert report["counts"]["new"] == 1
    assert report["attention"] == [{"row": 1, "reason": 'Decision: "Maybe" isn\'t one of the options.'}]
    assert session.exec(select(CustomValue)).all() == []


def test_keep_as_attaches_to_an_existing_field_with_the_same_name(session):
    field = cf.create_field(session, name="confirmation", type="text", at=NOW)
    session.commit()
    go(session, [row(confirm="Yes")], keep={"Confirmation": {"new": {"name": "Confirmation", "type": "text"}}})
    assert len(cf.list_fields(session)) == 1
    assert session.exec(select(CustomValue.value).where(CustomValue.field_id == field.id)).all() == ["Yes"]


def test_rows_without_employer_or_title_are_left_out(session):
    report = go(session, [row(employer=""), row(role=""), row()])
    assert report["counts"] == {"new": 1, "updated": 0, "unchanged": 0, "left_out": 2}
    assert [a["reason"] for a in report["attention"]] == ["No employer or title."] * 2


def test_failure_rolls_back_everything(session):
    sheet = Sheet("Job Master", COLUMNS, [row(), row("Contoso Health", "Analyst")])
    request = body(sheet, keep={"Confirmation": {"new": {"name": "Confirmation", "type": "text"}}},
                   status_words={"x": "Nonsense"})
    with pytest.raises(ImportFailure, match="Nonsense isn't a status JobMe knows."):
        run_import(session, sheet, request, now=NOW)
    session.rollback()
    assert jobs(session) == [] and cf.list_fields(session) == []


def test_an_error_partway_through_leaves_nothing_behind(session, monkeypatch):
    calls = []
    real = sheet_import._jobs_row

    def boom(run, rowno, r):
        calls.append(rowno)
        if rowno == 2:
            raise RuntimeError("disk on fire")
        return real(run, rowno, r)

    monkeypatch.setitem(sheet_import._HANDLERS, "jobs", boom)
    sheet = Sheet("Job Master", COLUMNS, [row(), row("Contoso Health", "Analyst")])
    request = body(sheet, keep={"Confirmation": {"new": {"name": "Confirmation", "type": "text"}}})
    with pytest.raises(RuntimeError):
        run_import(session, sheet, request, now=NOW)
    session.rollback()
    assert calls == [1, 2]
    assert jobs(session) == [] and session.exec(select(CustomField)).all() == []


def test_missing_required_mapping_and_unknown_column_are_refused(session):
    sheet = Sheet("Job Master", COLUMNS, [row()])
    with pytest.raises(ImportFailure, match="Choose which columns hold the employer and the job title."):
        run_import(session, sheet, body(sheet, mapping={"employer": "Employer"}), now=NOW)
    with pytest.raises(ImportFailure, match="That column isn't in the sheet: Nope"):
        run_import(session, sheet, body(sheet, mapping={"employer": "Employer", "title": "Nope"}), now=NOW)


def _xlsx(rows, headers=COLUMNS, name="Job Master"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = name
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_preview_route_returns_kinds_suggestions_and_column_info(client):
    data = _xlsx([row(status="APPLIED", confirm="Yes"), row("Contoso Health", "Analyst", confirm="Yes")])
    r = client.post("/api/import/sheet/preview", files={"file": ("book.xlsx", data)})
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out["kinds"]) == {"jobs", "applications", "contacts"}
    sheet = out["sheets"][0]
    assert sheet["guessed_kind"] == "jobs"
    assert sheet["suggested"]["jobs"]["employer"] == "Employer"
    assert sheet["columns_info"]["Confirmation"] == {"name": "Confirmation", "type": "choice", "choices": ["Yes"]}
    assert sheet["columns_info"]["Employer"]["type"] == "text"


def test_import_route_dry_run_then_real(client):
    data = _xlsx([row(status="APPLIED"), row("Contoso Health", "Analyst")])
    upload = client.post("/api/import/sheet/preview", files={"file": ("book.xlsx", data)}).json()
    mapping = {"employer": "Employer", "title": "Role", "status": "Application Status"}
    req = {"upload_id": upload["upload_id"], "sheet": "Job Master", "kind": "jobs", "mapping": mapping}
    dry = client.post("/api/import/sheet", json={**req, "dry_run": True})
    assert dry.status_code == 200 and dry.json()["counts"]["new"] == 2
    assert client.get("/api/jobs").json()["total"] == 0
    real = client.post("/api/import/sheet", json=req)
    assert real.status_code == 200 and real.json()["message"] == "Imported 2 new jobs, updated 0, 0 already in JobMe, 0 left out."
    assert client.get("/api/jobs").json()["total"] == 2
    again = client.post("/api/import/sheet", json=req).json()
    assert again["counts"] == {"new": 0, "updated": 0, "unchanged": 2, "left_out": 0}


def test_import_route_errors(client):
    data = _xlsx([row()])
    upload = client.post("/api/import/sheet/preview", files={"file": ("book.xlsx", data)}).json()
    base = {"upload_id": upload["upload_id"], "sheet": "Job Master", "kind": "jobs"}
    r = client.post("/api/import/sheet", json={**base, "mapping": {"employer": "Employer"}})
    assert r.status_code == 400
    assert r.json()["detail"] == "Choose which columns hold the employer and the job title."
    r = client.post("/api/import/sheet", json={"upload_id": "nope", "sheet": "x", "kind": "jobs", "mapping": {}})
    assert r.status_code == 404 and r.json()["detail"] == "That upload expired. Please upload the file again."
    r = client.post("/api/import/sheet/preview", files={"file": ("book.txt", b"hello")})
    assert r.status_code == 400
