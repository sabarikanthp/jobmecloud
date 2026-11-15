"""The run lock must work on Aurora DSQL, which has no SAVEPOINT and reports write conflicts at commit."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from jobmecloud.jobs import runlock
from jobmecloud.jobs.runlock import RunInProgressError, acquire_run_lock, release_run_lock

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


class _Orig(Exception):
    sqlstate = "40001"


@pytest.fixture
def statements(engine):
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    return seen


def test_taking_a_free_lock_uses_no_savepoint(engine, statements):
    acquire_run_lock(engine, NOW)
    assert not any("SAVEPOINT" in s.upper() for s in statements)


def test_contending_for_a_held_lock_uses_no_savepoint(engine, statements):
    acquire_run_lock(engine, NOW)
    with pytest.raises(RunInProgressError):
        acquire_run_lock(engine, NOW)
    assert not any("SAVEPOINT" in s.upper() for s in statements)


def test_stale_lock_can_be_taken_over_without_savepoint(engine, statements):
    acquire_run_lock(engine, NOW)
    owner = acquire_run_lock(engine, NOW + timedelta(minutes=11))
    assert owner and not any("SAVEPOINT" in s.upper() for s in statements)


def test_a_lock_released_between_the_attempts_is_taken(engine, monkeypatch):
    first = acquire_run_lock(engine, NOW)
    real_select_row = runlock._current_holder

    def released_just_before_we_look(conn):
        release_run_lock(engine, first)
        return real_select_row(conn)

    monkeypatch.setattr(runlock, "_current_holder", released_just_before_we_look)
    assert acquire_run_lock(engine, NOW)


def test_a_write_conflict_while_contending_means_someone_else_has_it(engine):
    acquire_run_lock(engine, NOW + timedelta(minutes=11))  # held, so the first insert fails
    with patch.object(runlock, "_current_holder", side_effect=OperationalError("select", {}, _Orig("conflict"))):
        with pytest.raises(RunInProgressError):
            acquire_run_lock(engine, NOW + timedelta(minutes=11))
