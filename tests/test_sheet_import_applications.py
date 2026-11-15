from datetime import date, datetime, timezone

from fakes import add_job
from sqlmodel import select

from jobmecloud.db.models import ActivityLog, Contact, FollowUp, Job
from jobmecloud.importers.sheet_import import SheetImportIn, run_import
from jobmecloud.importers.tracker import Sheet

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
COLUMNS = ["Employer", "Role", "Requisition", "Applied Date", "Current Status", "Recruiter / Contact",
           "Last Outreach", "Next Follow-up", "Response Date", "Interview Stage", "Notes"]
MAPPING = {"employer": "Employer", "title": "Role", "requisition": "Requisition",
           "applied_date": "Applied Date", "status": "Current Status", "contact": "Recruiter / Contact",
           "last_outreach": "Last Outreach", "next_followup": "Next Follow-up",
           "first_response_date": "Response Date", "interview_stage": "Interview Stage", "notes": "Notes"}


def row(employer="Northwind Labs", role="Data Engineer", req="", applied="", status="", contact="",
        outreach="", follow="", response="", stage="", notes=""):
    return [employer, role, req, applied, status, contact, outreach, follow, response, stage, notes]


def go(session, rows):
    sheet = Sheet("Applications & Followups", COLUMNS, rows)
    body = SheetImportIn(upload_id="u", sheet=sheet.name, kind="applications", mapping=MAPPING)
    report = run_import(session, sheet, body, now=NOW)
    session.commit()
    return report


def test_matched_row_fills_dates_status_followup_contact_and_notes(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer", status="New")
    report = go(session, [row(applied="2026-03-14", status="APPLIED", contact="Pat Recruiter",
                              outreach="2026-03-20", follow="2026-12-01", response="2026-03-25",
                              stage="Prescreen questionnaire completed", notes="Sent thank-you")])
    assert report["counts"] == {"new": 0, "updated": 1, "unchanged": 0, "left_out": 0}
    job = session.get(Job, jid)
    assert job.status == "Applied" and job.applied_at.date() == date(2026, 3, 14)
    assert job.first_response_at.date() == date(2026, 3, 25)
    assert "Interview stage: Prescreen questionnaire completed" in job.notes
    assert "Sent thank-you" in job.notes
    [fu] = session.exec(select(FollowUp)).all()
    assert (fu.job_id, fu.due_date, fu.status, fu.type) == (jid, date(2026, 12, 1), "Open", "Other")
    [contact] = session.exec(select(Contact)).all()
    assert (contact.job_id, contact.name, contact.employer) == (jid, "Pat Recruiter", "Northwind Labs")
    notes = session.exec(select(ActivityLog).where(ActivityLog.job_id == jid, ActivityLog.action == "note")).all()
    assert [(n.note, n.actor, n.at.date()) for n in notes] == [("Outreach", "user", date(2026, 3, 20))]


def test_reimport_creates_nothing_twice(session):
    add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer", status="New")
    rows = [row(applied="2026-03-14", status="APPLIED", contact="Pat Recruiter", outreach="2026-03-20",
                follow="2026-12-01", stage="Prescreen", notes="Sent thank-you")]
    go(session, rows)
    before = (session.exec(select(Job)).one().notes, len(session.exec(select(ActivityLog)).all()))
    again = go(session, rows)
    assert again["counts"] == {"new": 0, "updated": 0, "unchanged": 1, "left_out": 0}
    assert len(session.exec(select(FollowUp)).all()) == 1
    assert len(session.exec(select(Contact)).all()) == 1
    assert (session.exec(select(Job)).one().notes, len(session.exec(select(ActivityLog)).all())) == before


def test_a_finished_followup_is_not_recreated_on_reimport(session):
    add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer")
    rows = [row(follow="2026-12-01")]
    go(session, rows)
    fu = session.exec(select(FollowUp)).one()
    fu.status = "Done"
    session.add(fu)
    session.commit()
    go(session, rows)
    assert len(session.exec(select(FollowUp)).all()) == 1


def test_unmatched_row_becomes_a_new_job_and_is_listed(session):
    report = go(session, [row("Contoso Health", "Analyst", status="APPLIED", applied="2026-03-01")])
    assert report["counts"]["new"] == 1
    assert report["attention"] == [{"row": 1, "reason": "New from this sheet."}]
    job = session.exec(select(Job)).one()
    assert (job.employer, job.status, job.origin) == ("Contoso Health", "Applied", "import")


def test_a_row_matching_two_jobs_is_left_out(session):
    e = session.get_bind()
    add_job(e, employer="Northwind Labs", title="Data Engineer", location="Austin, TX")
    add_job(e, employer="Northwind Labs", title="Data Engineer", location="Boston, MA")
    report = go(session, [row(follow="2026-12-01", contact="Pat")])
    assert report["counts"]["left_out"] == 1
    assert session.exec(select(FollowUp)).all() == [] and session.exec(select(Contact)).all() == []


def test_unreadable_followup_and_outreach_text_lands_in_the_notes(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer")
    go(session, [row(follow="after the holidays", outreach="last week")])
    notes = session.get(Job, jid).notes
    assert "Next follow-up in file: after the holidays" in notes
    assert "Last outreach in file: last week" in notes
    assert session.exec(select(FollowUp)).all() == []


def test_existing_contact_with_the_same_name_is_not_duplicated(session):
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer")
    session.add(Contact(job_id=jid, name="pat recruiter", employer="Northwind Labs"))
    session.commit()
    go(session, [row(contact="Pat Recruiter")])
    assert len(session.exec(select(Contact)).all()) == 1


def test_a_followup_the_user_already_has_for_that_day_is_not_duplicated(session):
    from jobmecloud.jobs.followups import create_followup
    jid = add_job(session.get_bind(), employer="Northwind Labs", title="Data Engineer")
    create_followup(session, type="Recruiter outreach", due=date(2026, 12, 1), at=NOW, job_id=jid,
                    note="My own reminder")
    session.commit()
    go(session, [row(follow="2026-12-01")])
    assert len(session.exec(select(FollowUp)).all()) == 1
