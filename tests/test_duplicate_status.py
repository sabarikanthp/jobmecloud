from datetime import datetime, timezone

import pytest
from fakes import add_job
from sqlmodel import Session

from jobmecloud.db.models import ActivityLog, Job
from jobmecloud.jobs.tracking import TrackingError, allowed_next, change_status, reopen

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def job(session, status="New", **kw):
    j = Job(employer="Northwind Labs", title="Data Engineer", origin="manual", status=status, first_seen_at=NOW, **kw)
    session.add(j)
    session.commit()
    return j


def test_duplicate_is_offered_on_new_ready_and_closed_jobs_only(session):
    for status in ("New", "Ready", "Closed"):
        assert "Duplicate" in allowed_next(job(session, status))
    for status in ("Applied", "Interviewing", "Offer", "Accepted", "Rejected", "Skipped", "Withdrawn", "Unavailable"):
        assert "Duplicate" not in allowed_next(job(session, status))


def test_marking_a_duplicate_records_the_original_and_logs_it(session):
    original, dupe = job(session, "Applied"), job(session)
    change_status(session, dupe, "Duplicate", actor="user", at=NOW, duplicate_of=original.id, note="Same posting")
    assert (dupe.status, dupe.repost_of_id) == ("Duplicate", original.id)
    assert allowed_next(dupe) == ["Reopen"]
    session.commit()
    entry = session.exec(__import__("sqlmodel").select(ActivityLog).where(ActivityLog.job_id == dupe.id)).one()
    assert (entry.to_value, entry.note) == ("Duplicate", "Same posting")


def test_a_duplicate_needs_an_existing_job_that_is_not_itself(session):
    dupe = job(session)
    for bad in (None, 99999, dupe.id):
        with pytest.raises(TrackingError):
            change_status(session, dupe, "Duplicate", actor="user", at=NOW, duplicate_of=bad)
    assert dupe.status == "New"


def test_a_duplicate_of_a_duplicate_points_at_the_real_original(session):
    original = job(session, "Applied")
    middle = job(session)
    change_status(session, middle, "Duplicate", actor="user", at=NOW, duplicate_of=original.id)
    last = job(session)
    change_status(session, last, "Duplicate", actor="user", at=NOW, duplicate_of=middle.id)
    assert last.repost_of_id == original.id


def test_reopening_a_duplicate_forgets_the_link(session):
    original, dupe = job(session), job(session)
    change_status(session, dupe, "Duplicate", actor="user", at=NOW, duplicate_of=original.id)
    reopen(session, dupe, at=NOW)
    assert (dupe.status, dupe.repost_of_id) == ("New", None)


def test_the_status_route_takes_duplicate_of(client, engine):
    original, dupe = add_job(engine, status="Applied"), add_job(engine)
    r = client.post(f"/api/jobs/{dupe}/status", json={"status": "Duplicate", "duplicate_of": original})
    assert r.status_code == 200 and r.json()["status"] == "Duplicate"
    detail = client.get(f"/api/jobs/{dupe}").json()
    assert detail["duplicate_of"]["id"] == original and detail["duplicate_of"]["status"] == "Applied"
    assert [x["id"] for x in client.get(f"/api/jobs/{original}").json()["also_seen_as"]] == [dupe]
    assert client.post(f"/api/jobs/{dupe}/status", json={"status": "Duplicate"}).status_code == 400
