import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from jobmecloud.db.models import RunLock
from jobmecloud.jobs.runlock import (
    STALE_AFTER,
    RunInProgressError,
    acquire_run_lock,
    lock_heartbeat,
    release_run_lock,
    run_lock_held,
    touch_run_lock,
)

NOW = datetime(2026, 11, 13, 6, tzinfo=timezone.utc)


def test_a_lock_is_stale_ten_minutes_after_its_last_heartbeat(engine):
    owner = acquire_run_lock(engine, NOW)
    with pytest.raises(RunInProgressError):
        acquire_run_lock(engine, NOW + timedelta(minutes=9))
    assert touch_run_lock(engine, owner, NOW + timedelta(minutes=9))
    assert run_lock_held(engine, NOW + timedelta(minutes=18))
    with pytest.raises(RunInProgressError):
        acquire_run_lock(engine, NOW + timedelta(minutes=18))
    assert not run_lock_held(engine, NOW + timedelta(minutes=20))
    assert acquire_run_lock(engine, NOW + timedelta(minutes=20))


def test_a_lock_that_never_beat_is_stale_ten_minutes_after_acquire(engine):
    acquire_run_lock(engine, NOW)
    assert STALE_AFTER == timedelta(minutes=10)
    assert run_lock_held(engine, NOW + timedelta(minutes=9, seconds=59))
    assert not run_lock_held(engine, NOW + timedelta(minutes=10))


def test_release_with_a_stale_owner_does_not_delete_the_new_owners_lock(engine):
    first = acquire_run_lock(engine, NOW)
    later = NOW + timedelta(minutes=30)
    second = acquire_run_lock(engine, later)
    assert first != second
    release_run_lock(engine, first)
    assert run_lock_held(engine, later)
    release_run_lock(engine, second)
    assert not run_lock_held(engine, later)


def test_touch_only_works_for_the_current_owner(engine):
    first = acquire_run_lock(engine, NOW)
    second = acquire_run_lock(engine, NOW + timedelta(minutes=30))
    assert not touch_run_lock(engine, first, NOW + timedelta(minutes=31))
    assert touch_run_lock(engine, second, NOW + timedelta(minutes=31))


def test_release_without_an_owner_still_deletes(engine):
    acquire_run_lock(engine, NOW)
    release_run_lock(engine)
    assert not run_lock_held(engine, NOW)


def test_heartbeat_thread_touches_the_lock_and_stops(engine):
    owner = acquire_run_lock(engine, NOW)
    with lock_heartbeat(engine, owner, interval=0.05) as beat:
        time.sleep(0.4)
        with engine.connect() as conn:
            row = conn.execute(select(RunLock.__table__.c.heartbeat_at)).scalar()
        assert row is not None
    assert not beat.thread.is_alive()
