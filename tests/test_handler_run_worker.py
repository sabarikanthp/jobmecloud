from datetime import datetime, timezone

from fakes import NOW, FakeProvider, deps, extract_json, rec, score_json, setup_profile, tool_reply
from sqlmodel import Session, select

from jobmecloud.agents.jobscout.pipeline import STOPPED_EARLY_COPY, execute_run, start_run
from jobmecloud.db.models import Run
from jobmecloud.handlers import run_worker
from jobmecloud.jobs.runlock import run_lock_held


class Ctx:
    def __init__(self, remaining_ms=900_000):
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self.remaining_ms


def one_job_provider():
    return FakeProvider(replies=[
        tool_reply(rec("https://northwind.example/1", "Northwind Labs", "Senior Data Engineer")),
        "done", extract_json(), score_json(90)])


def test_time_is_short_before_the_lambda_limit():
    assert run_worker.time_is_short(Ctx(60_000)) is True
    assert run_worker.time_is_short(Ctx(120_000)) is False


def test_run_event_executes_the_started_run(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    monkeypatch.setattr(run_worker, "build_deps", lambda context: deps(one_job_provider()))
    run_id = start_run(engine, "manual", datetime.now(timezone.utc))
    run_worker.handler({"task": "run", "run_id": run_id}, Ctx())
    with Session(engine) as s:
        run = s.get(Run, run_id)
    assert run.finished_at is not None and (run.found, run.matched) == (1, 1)
    assert not run_lock_held(engine, datetime.now(timezone.utc))


def test_schedule_event_starts_and_executes_a_scheduled_run(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    monkeypatch.setattr(run_worker, "build_deps", lambda context: deps(one_job_provider()))
    run_worker.handler({"trigger": "schedule"}, Ctx())
    with Session(engine) as s:
        run = s.exec(select(Run)).one()
    assert run.trigger == "schedule" and run.finished_at is not None and run.matched == 1


def test_schedule_event_during_manual_run_skips_with_note(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    monkeypatch.setattr(run_worker, "build_deps", lambda context: deps(FakeProvider()))
    manual = start_run(engine, "manual", datetime.now(timezone.utc))
    run_worker.handler({"trigger": "schedule"}, Ctx())
    with Session(engine) as s:
        runs = s.exec(select(Run).order_by(Run.id)).all()
    assert [r.trigger for r in runs] == ["manual", "schedule"]
    assert runs[1].errors == ["Skipped: a run was already in progress."] and runs[1].finished_at is not None
    assert runs[0].finished_at is None and run_lock_held(engine, datetime.now(timezone.utc))
    assert runs[0].id == manual


def test_schedule_event_with_setup_problem_leaves_a_failed_run(data_dir, engine, monkeypatch):
    monkeypatch.setattr(run_worker, "build_deps", lambda context: deps(FakeProvider()))
    run_worker.handler({"trigger": "schedule"}, Ctx())
    with Session(engine) as s:
        run = s.exec(select(Run)).one()
    assert run.finished_at is not None and run.errors == ["Connect an AI first."]


def test_pipeline_stops_cleanly_when_time_is_short(data_dir, engine):
    setup_profile(data_dir)
    d = deps(FakeProvider(replies=[tool_reply(rec("https://a.example/1", "A", "Data Engineer"),
                                              rec("https://b.example/2", "B", "Data Engineer")), "done"]))
    d.should_stop = lambda: True
    run_id = start_run(engine, "manual", NOW)
    run = execute_run(data_dir, engine, run_id, d, NOW)
    assert run.errors.count(STOPPED_EARLY_COPY) == 1
    assert run.finished_at is not None and run.new == 0 and not run_lock_held(engine, NOW)
