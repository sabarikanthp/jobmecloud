from datetime import timedelta

from fakes import FakeProvider, NOW, deps, setup_profile
from sqlmodel import Session, select

from jobmecloud.agents.jobscout import pipeline
from jobmecloud.agents.jobscout.pipeline import execute_run, start_run
from jobmecloud.db.models import Run, RunLock
from jobmecloud.jobs.runlock import acquire_run_lock, run_lock_held


def _lock_owner(engine):
    with Session(engine) as s:
        return s.exec(select(RunLock.owner)).first()


def test_start_run_records_the_lock_owner(engine):
    run_id = start_run(engine, "manual", NOW)
    with Session(engine) as s:
        owner = s.get(Run, run_id).lock_owner
    assert owner and owner == _lock_owner(engine)


def test_a_finished_run_releases_its_lock(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    monkeypatch.setattr(pipeline, "_search", lambda ctx: [])
    run_id = start_run(engine, "manual", NOW)
    execute_run(data_dir, engine, run_id, deps(FakeProvider()), NOW)
    assert not run_lock_held(engine, NOW)


def test_a_late_run_does_not_release_a_lock_that_was_taken_over(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    monkeypatch.setattr(pipeline, "_search", lambda ctx: [])
    run_id = start_run(engine, "manual", NOW)
    later = NOW + timedelta(hours=1)  # the first run looks dead, so a second one takes over
    newer = acquire_run_lock(engine, later)
    execute_run(data_dir, engine, run_id, deps(FakeProvider()), NOW)
    assert run_lock_held(engine, later)
    assert _lock_owner(engine) == newer


def test_the_run_keeps_the_lock_alive_while_it_works(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    seen = {}

    def slow_search(ctx):
        import time
        time.sleep(0.4)
        with Session(engine) as s:
            seen["beat"] = s.exec(select(RunLock.heartbeat_at)).first()
        return []

    monkeypatch.setattr(pipeline, "_search", slow_search)
    monkeypatch.setattr(pipeline, "HEARTBEAT_SECONDS", 0.05)
    run_id = start_run(engine, "manual", NOW)
    execute_run(data_dir, engine, run_id, deps(FakeProvider()), NOW)
    assert seen["beat"] is not None


def test_a_run_that_lost_its_lock_stops_between_stages(data_dir, engine, monkeypatch):
    import time

    import pytest
    from sqlalchemy import update

    setup_profile(data_dir)
    monkeypatch.setattr(pipeline, "HEARTBEAT_SECONDS", 0.05)
    called = []

    def search(ctx):
        with engine.begin() as conn:  # a newer run takes over while this one was asleep
            conn.execute(update(RunLock.__table__).values(owner="someone-else"))
        time.sleep(0.4)
        return []

    monkeypatch.setattr(pipeline, "_search", search)
    monkeypatch.setattr(pipeline, "_prepare_docs", lambda ctx: called.append("docs"))
    run_id = start_run(engine, "manual", NOW)
    with pytest.raises(pipeline.RunLostError):
        execute_run(data_dir, engine, run_id, deps(FakeProvider()), NOW)
    assert called == []
    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run.finished_at is not None and "another run took over" in run.errors[0]
    assert _lock_owner(engine) == "someone-else"  # the newer run's lock is untouched
