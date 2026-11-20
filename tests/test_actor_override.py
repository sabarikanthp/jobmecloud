from datetime import date, datetime, timezone

from sqlmodel import select

from jobmecloud.db.models import ActivityLog, Job
from jobmecloud.jobs import followups, tracking
from jobmecloud.jobs.actor import acting_as

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def make_job(session, status="New") -> Job:
    j = Job(employer="Northwind Labs", title="Data Engineer", origin="scout", status=status, first_seen_at=NOW)
    session.add(j)
    session.commit()
    return j


def actors(session):
    return [r.actor for r in session.exec(select(ActivityLog).order_by(ActivityLog.id))]


def test_status_change_logs_label_inside_acting_as(session):
    job = make_job(session)
    with acting_as("claude:Desktop"):
        tracking.change_status(session, job, "Applied", actor="user", at=NOW)
    session.commit()
    assert "claude:Desktop" in actors(session)


def test_followup_created_logs_label(session):
    job = make_job(session, "Applied")
    with acting_as("claude:Desktop"):
        followups.create_followup(session, type="Other", due=date(2026, 11, 20), at=NOW, job_id=job.id)
    session.commit()
    assert actors(session)[-1] == "claude:Desktop"


def test_system_actor_is_never_overridden(session):
    job = make_job(session)
    with acting_as("claude:Desktop"):
        tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="x", at=NOW, actor="system")
    assert actors(session) == ["system"]


def test_no_label_outside_context(session):
    job = make_job(session)
    tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="x", at=NOW)
    assert actors(session) == ["user"]


def test_label_resets_after_context(session):
    job = make_job(session)
    with acting_as("claude:Desktop"):
        pass
    tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="x", at=NOW)
    assert actors(session) == ["user"]
