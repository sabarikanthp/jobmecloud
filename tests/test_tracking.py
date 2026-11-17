from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select, text

from jobmecloud.db.models import ActivityLog, Job
from jobmecloud.jobs.tracking import TrackingError, allowed_next, change_status, reopen

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def job(status="New", **kw):
    return Job(employer="Northwind Labs", title="Data Engineer", origin="scout", status=status,
               first_seen_at=NOW, **kw)


def test_apply_sets_applied_date_as_utc_midnight_and_logs(session):
    j = job(); session.add(j); session.commit()
    change_status(session, j, "Applied", actor="user", at=NOW, on=date(2026, 11, 10))
    assert (j.status, j.applied_at) == ("Applied", datetime(2026, 11, 10, tzinfo=timezone.utc))
    row = session.exec(select(ActivityLog)).one()
    assert (row.entity_type, row.entity_id, row.job_id, row.action, row.from_value, row.to_value, row.actor) == \
           ("job", j.id, j.id, "status_changed", "New", "Applied", "user")


def test_response_and_outcome_dates(session):
    j = job(); session.add(j); session.commit()
    change_status(session, j, "Applied", actor="user", at=NOW, on=date(2026, 11, 1))
    change_status(session, j, "Interviewing", actor="user", at=NOW, on=date(2026, 11, 5))
    change_status(session, j, "Offer", actor="user", at=NOW, on=date(2026, 11, 9))
    assert j.first_response_at == datetime(2026, 11, 5, tzinfo=timezone.utc)      # set once, kept
    assert j.outcome_at is None
    change_status(session, j, "Rejected", actor="user", at=NOW, on=date(2026, 11, 10))
    assert (j.status, j.outcome_at) == ("Rejected", datetime(2026, 11, 10, tzinfo=timezone.utc))
    skipped = job(); session.add(skipped); session.commit()
    change_status(session, skipped, "Skipped", actor="user", at=NOW, skip_reason="Other", skip_reasons=["Other"])
    assert skipped.first_response_at is None and skipped.outcome_at is not None


def test_skip_needs_a_listed_reason(session):
    j = job(); session.add(j); session.commit()
    for bad in (None, "", "  ", "Boring"):
        with pytest.raises(TrackingError, match="Choose why you're skipping this job."):
            change_status(session, j, "Skipped", actor="user", at=NOW, skip_reason=bad, skip_reasons=["Pay too low", "Other"])
    assert j.status == "New" and session.exec(select(ActivityLog)).all() == []
    change_status(session, j, "Skipped", actor="user", at=NOW, skip_reason="Pay too low", skip_note="Under 150k", skip_reasons=["Pay too low", "Other"])
    assert (j.status, j.skip_reason, j.skip_note) == ("Skipped", "Pay too low", "Under 150k")


@pytest.mark.parametrize("status,to", [("Applied", "Skipped"), ("Accepted", "Applied"), ("Interviewing", "Applied"), ("New", "Offer")])
def test_disallowed_changes_raise_and_change_nothing(session, status, to):
    j = job(status); session.add(j); session.commit()
    with pytest.raises(TrackingError, match=f"isn't available for a job that is {status}"):
        change_status(session, j, to, actor="user", at=NOW, skip_reason="Other", skip_reasons=["Other"])
    assert j.status == status


def test_closed_job_can_still_be_marked_applied_and_system_never_closes_applied(session):
    closed = job("Closed"); applied = job("Applied"); session.add_all([closed, applied]); session.commit()
    change_status(session, closed, "Applied", actor="user", at=NOW)
    change_status(session, applied, "Closed", actor="system", at=NOW)
    assert (closed.status, applied.status) == ("Applied", "Applied")


def test_future_date_refused(session):
    j = job(); session.add(j); session.commit()
    with pytest.raises(TrackingError, match="That date is in the future."):
        change_status(session, j, "Applied", actor="user", at=NOW, on=NOW.astimezone().date() + timedelta(days=1))
    assert j.status == "New" and session.exec(select(ActivityLog)).all() == []


def test_reopen(session):
    j = job("Skipped", skip_reason="Other", skip_note="n", docs_folder="C:/x", outcome_at=NOW)
    session.add(j); session.commit()
    reopen(session, j, at=NOW)
    assert (j.status, j.skip_reason, j.skip_note, j.outcome_at) == ("Ready", None, None, None)
    assert session.exec(select(ActivityLog)).one().action == "reopened"
    with pytest.raises(TrackingError):
        reopen(session, job("Applied"), at=NOW)


def test_allowed_next():
    assert allowed_next(job("Applied")) == ["Interviewing", "Offer", "Rejected", "Withdrawn", "Unavailable"]
    assert allowed_next(job("Closed")) == ["Applied", "Reopen"] and allowed_next(job("Accepted")) == []


def test_log_columns_are_nullable_in_the_database(session):
    cols = {}
    for table in ("activitylog", "followup"):
        rows = session.exec(text(f"PRAGMA table_info({table})")).all()
        cols[table] = {r[1]: r[3] for r in rows}  # name -> notnull flag
    for c in ("entity_type", "entity_id", "action", "at", "actor"):
        assert cols["activitylog"][c] == 0
    for c in ("type", "due_date", "status", "created_at"):
        assert cols["followup"][c] == 0


def test_change_status_does_not_commit(session):
    j = job(); session.add(j); session.commit()
    change_status(session, j, "Applied", actor="user", at=NOW, on=date(2026, 11, 10))
    session.rollback()
    assert session.exec(select(ActivityLog)).all() == []


@pytest.mark.parametrize("start", ["New", "Ready", "Applied", "Interviewing"])
def test_a_job_can_be_marked_unavailable_by_hand_and_reopened(session, start):
    j = job(start); session.add(j); session.commit()
    assert "Unavailable" in allowed_next(j)
    change_status(session, j, "Unavailable", actor="user", at=NOW, on=date(2026, 11, 10), note="Posting taken down")
    assert (j.status, j.outcome_at) == ("Unavailable", datetime(2026, 11, 10, tzinfo=timezone.utc))
    assert allowed_next(j) == ["Reopen"]
    reopen(session, j, at=NOW)
    assert j.status == "New" and j.outcome_at is None


def test_unavailable_is_not_offered_once_the_job_has_an_outcome(session):
    for status in ("Offer", "Accepted", "Rejected", "Skipped", "Withdrawn", "Closed"):
        assert "Unavailable" not in allowed_next(job(status))


def test_the_app_never_marks_a_job_unavailable_on_its_own(session):
    j = job(); session.add(j); session.commit()
    change_status(session, j, "Unavailable", actor="system", at=NOW)
    assert j.status == "New"
