from datetime import datetime, timedelta, timezone

import pytest

from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate
from jobmecloud.jobs.runlock import (
    STALE_AFTER,
    RunInProgressError,
    acquire_run_lock,
    release_run_lock,
    run_lock_held,
)

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def test_second_lock_refused_until_released(tmp_path):
    engine = make_engine(data_dir=tmp_path)
    migrate(engine)
    acquire_run_lock(engine, NOW)
    with pytest.raises(RunInProgressError, match="A run is already in progress."):
        acquire_run_lock(engine, NOW + timedelta(minutes=5))
    assert run_lock_held(engine, NOW)
    release_run_lock(engine)
    assert not run_lock_held(engine, NOW)
    acquire_run_lock(engine, NOW)
    engine.dispose()


def test_stale_lock_is_taken_over(tmp_path):
    engine = make_engine(data_dir=tmp_path)
    migrate(engine)
    acquire_run_lock(engine, NOW)
    later = NOW + STALE_AFTER + timedelta(minutes=1)
    assert not run_lock_held(engine, later)
    acquire_run_lock(engine, later)
    with pytest.raises(RunInProgressError):
        acquire_run_lock(engine, later)
    engine.dispose()


def test_lock_shared_between_engines(tmp_path):
    a = make_engine(data_dir=tmp_path)
    migrate(a)
    b = make_engine(data_dir=tmp_path)
    acquire_run_lock(a, NOW)
    with pytest.raises(RunInProgressError):
        acquire_run_lock(b, NOW)
    a.dispose()
    b.dispose()
