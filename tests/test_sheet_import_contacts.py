from datetime import datetime, timezone

from fakes import add_job
from sqlmodel import select

from jobmecloud.db.models import ActivityLog, Contact, FollowUp
from jobmecloud.importers.sheet_import import SheetImportIn, run_import
from jobmecloud.importers.tracker import Sheet
from jobmecloud.jobs.tracking import local_date

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
COLUMNS = ["Employer / Network", "Contact", "Related Role", "Outreach Date", "Contact / Referral Status",
           "Next Action", "Source"]
MAPPING = {"name": "Contact", "employer": "Employer / Network", "related_role": "Related Role",
           "outreach_date": "Outreach Date", "status_text": "Contact / Referral Status",
           "next_action": "Next Action", "source": "Source"}


def row(employer="Northwind Labs", name="Jordan Example", role="", outreach="", status="", action="",
        source=""):
    return [employer, name, role, outreach, status, action, source]


def go(session, rows):
    sheet = Sheet("Contacts & Referrals", COLUMNS, rows)
    body = SheetImportIn(upload_id="u", sheet=sheet.name, kind="contacts", mapping=MAPPING)
    report = run_import(session, sheet, body, now=NOW)
    session.commit()
    return report


def test_new_contact_with_linked_job_notes_and_followup(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer")
    report = go(session, [row(role="Data Engineer", outreach="2026-10-28", status="Contacted (user confirmed)",
                              action="Send a thank-you note", source="Nov 2 addendum")])
    assert report["counts"] == {"new": 1, "updated": 0, "unchanged": 0, "left_out": 0}
    [c] = session.exec(select(Contact)).all()
    assert (c.name, c.employer, c.job_id, c.status) == ("Jordan Example", "Northwind Labs", jid, "Contacted")
    assert c.notes == "Status: Contacted (user confirmed)\nOutreach: 2026-10-28\nSource: Nov 2 addendum"
    [fu] = session.exec(select(FollowUp)).all()
    assert (fu.contact_id, fu.job_id, fu.type, fu.status, fu.note) == (
        c.id, jid, "Other", "Open", "Send a thank-you note")
    assert fu.due_date == local_date(NOW)
    assert "contact_added" in [r.action for r in session.exec(select(ActivityLog))]


def test_reimport_changes_nothing(session):
    add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer")
    rows = [row(role="Data Engineer", outreach="2026-10-28", status="Replied", action="Call back", source="Src")]
    go(session, rows)
    before = (session.exec(select(Contact)).one().notes, len(session.exec(select(ActivityLog)).all()))
    again = go(session, rows)
    assert again["counts"] == {"new": 0, "updated": 0, "unchanged": 1, "left_out": 0}
    assert len(session.exec(select(Contact)).all()) == 1 and len(session.exec(select(FollowUp)).all()) == 1
    assert (session.exec(select(Contact)).one().notes, len(session.exec(select(ActivityLog)).all())) == before


def test_a_name_only_row_imports(session):
    report = go(session, [row(employer="", name="Sam Example")])
    assert report["counts"]["new"] == 1
    [c] = session.exec(select(Contact)).all()
    assert (c.name, c.employer, c.job_id, c.notes, c.status) == ("Sam Example", None, None, None, None)
    assert session.exec(select(FollowUp)).all() == []


def test_status_words_set_the_status_only_when_clear(session):
    go(session, [row(name="A", status="Contacted (user confirmed)"),
                 row(name="B", status="Connection invitation SENT Nov 2; pending response"),
                 row(name="C", status="Invitation sent earlier; accepted Oct 30"),
                 row(name="D", status="They replied on Nov 5")])
    status = {c.name: c.status for c in session.exec(select(Contact))}
    assert status == {"A": "Contacted", "B": None, "C": None, "D": "Replied"}


def test_unlinked_related_role_is_listed(session):
    add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer", location="Austin, TX")
    add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer", location="Boston, MA")
    report = go(session, [row(role="Data Engineer"), row(name="Pat", role="Chief Wizard")])
    assert [a["reason"] for a in report["attention"]] == [
        'No single job matches "Data Engineer".', 'No single job matches "Chief Wizard".']
    assert [c.job_id for c in session.exec(select(Contact))] == [None, None]


def test_existing_contact_fills_empty_fields_only(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer")
    session.add(Contact(name="  jordan   EXAMPLE", employer="northwind labs inc", notes="My note",
                        status="Meeting set"))
    session.commit()
    report = go(session, [row(role="Data Engineer", status="Contacted", outreach="2026-10-28")])
    assert report["counts"] == {"new": 0, "updated": 1, "unchanged": 0, "left_out": 0}
    [c] = session.exec(select(Contact)).all()
    assert c.job_id == jid and c.status == "Meeting set"
    assert c.notes == "My note\nStatus: Contacted\nOutreach: 2026-10-28"


def test_missing_name_is_left_out_and_keep_columns_are_ignored(session):
    report = go(session, [row(name=""), row(name="Sam")])
    assert report["counts"] == {"new": 1, "updated": 0, "unchanged": 0, "left_out": 1}
    assert report["attention"] == [{"row": 1, "reason": "No name."}]
    assert report["sample"][0]["title"] == "Sam"


def test_unreadable_outreach_date_is_kept_as_text(session):
    go(session, [row(outreach="early November")])
    assert session.exec(select(Contact)).one().notes == "Outreach in file: early November"
