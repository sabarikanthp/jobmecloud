from datetime import date, datetime, timezone

import pytest
from sqlmodel import select

from jobmecloud.db.models import ActivityLog, FollowUp, Job
from jobmecloud.jobs.followups import (
    bucket, cancel, complete, create_followup, create_for_applied, reschedule, snooze,
)
from jobmecloud.jobs.tracking import TrackingError

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def make_job(session, status="Applied") -> Job:
    j = Job(employer="Northwind Labs", title="Data Engineer", origin="scout", status=status,
            first_seen_at=NOW)
    session.add(j)
    session.commit()
    return j


@pytest.fixture
def job_id(session):
    return make_job(session).id


def test_buckets():
    fu = lambda s, d: FollowUp(type="Other", due_date=d, status=s, created_at=NOW, job_id=1)
    t = date(2026, 11, 12)
    assert [bucket(fu("Open", d), t) for d in (date(2026, 11, 11), t, date(2026, 11, 13))] == ["overdue", "today", "upcoming"]
    assert bucket(fu("Snoozed", date(2026, 11, 20)), t) == "upcoming" and bucket(fu("Done", date(2026, 1, 1)), t) == "done"
    assert bucket(fu("Cancelled", date(2026, 11, 20)), t) == "done"


def test_auto_check_in_once_and_can_be_turned_off(session):
    j = make_job(session)
    other_job = make_job(session)
    f = create_for_applied(session, j, default_days=7, applied_on=date(2026, 11, 10), at=NOW)
    assert (f.type, f.due_date, f.status) == ("Application check-in", date(2026, 11, 17), "Open")
    assert create_for_applied(session, j, default_days=7, applied_on=date(2026, 11, 10), at=NOW) is None
    assert create_for_applied(session, other_job, default_days=None, applied_on=date(2026, 11, 10), at=NOW) is None
    assert create_for_applied(session, other_job, default_days=0, applied_on=date(2026, 11, 10), at=NOW) is None


def test_snooze_reschedule_rules(session, job_id):
    t = date(2026, 11, 12)
    fu = create_followup(session, type="Other", due=t, at=NOW, job_id=job_id)
    with pytest.raises(TrackingError, match="Pick today or a later date."):
        snooze(session, fu, until=date(2026, 11, 11), today=t, at=NOW)
    snooze(session, fu, until=date(2026, 11, 20), today=t, at=NOW)
    assert (fu.status, fu.due_date) == ("Snoozed", date(2026, 11, 20))
    reschedule(session, fu, due=date(2026, 11, 14), today=t, at=NOW)
    assert (fu.status, fu.due_date) == ("Open", date(2026, 11, 14))
    complete(session, fu, at=NOW, outcome_note="Sent")
    assert (fu.status, fu.outcome_note, fu.completed_at) == ("Done", "Sent", NOW)
    for act in (lambda: complete(session, fu, at=NOW), lambda: snooze(session, fu, until=t, today=t, at=NOW),
                lambda: reschedule(session, fu, due=t, today=t, at=NOW), lambda: cancel(session, fu, at=NOW)):
        with pytest.raises(TrackingError, match="That follow-up is already finished."):
            act()


def test_every_action_is_logged(session, job_id):
    t = date(2026, 11, 12)
    fu = create_followup(session, type="Other", due=t, at=NOW, job_id=job_id)
    snooze(session, fu, until=date(2026, 11, 15), today=t, at=NOW)
    reschedule(session, fu, due=date(2026, 11, 16), today=t, at=NOW)
    cancel(session, fu, at=NOW)
    rows = session.exec(select(ActivityLog).where(ActivityLog.entity_type == "followup")).all()
    assert [r.action for r in rows] == ["followup_created", "followup_snoozed", "followup_rescheduled", "followup_cancelled"]
    assert {r.job_id for r in rows} == {job_id} and {r.entity_id for r in rows} == {fu.id}


def test_create_needs_a_target_and_a_known_type(session, job_id):
    with pytest.raises(TrackingError, match="A follow-up needs a job or a contact."):
        create_followup(session, type="Other", due=date(2026, 11, 12), at=NOW)
    with pytest.raises(TrackingError, match="Choose a type of follow-up."):
        create_followup(session, type="Nag", due=date(2026, 11, 12), at=NOW, job_id=job_id)


def test_create_rejects_unknown_job_or_contact(session, job_id):
    with pytest.raises(TrackingError, match="That job no longer exists."):
        create_followup(session, type="Other", due=date(2026, 11, 12), at=NOW, job_id=9999)
    with pytest.raises(TrackingError, match="That contact no longer exists."):
        create_followup(session, type="Other", due=date(2026, 11, 12), at=NOW, contact_id=9999)
    assert session.exec(select(FollowUp)).all() == []
    assert session.exec(select(ActivityLog)).all() == []
