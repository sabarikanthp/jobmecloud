import json
from datetime import datetime, timezone

import boto3
from inbound_fixtures import make_email

from fakes import NOW, FakeProvider, deps, extract_json, rec, score_json, setup_profile, tool_reply
from sqlmodel import Session, select

from jobmecloud.agents.jobscout.pipeline import STOPPED_EARLY_COPY, execute_run, start_run
from jobmecloud.config.profile import SearchProfile, save_search
from jobmecloud.db.models import Job, Run
from jobmecloud.inbound import store
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


# ---------------------------------------------------------------- runs started by an email

EMAIL_KEY = "inbound/abc123"


def put_email(monkeypatch, body="Strong lead: Northwind Labs https://a.example/1", key=EMAIL_KEY):
    boto3.client("s3").create_bucket(Bucket="inbox")
    boto3.client("s3").put_object(Bucket="inbox", Key=key, Body=make_email(text=body))
    monkeypatch.setenv("JOBMECLOUD_INBOX_BUCKET", "inbox")


def roles(*items):
    return json.dumps({"roles": [
        {"employer": "Northwind Labs", "title": "Senior Data Engineer", "url": "https://a.example/1",
         "requisition_id": "", "verdict": "consider", "note": "", **i} for i in items]})


def email_run(engine, monkeypatch, provider, *, record=True):
    monkeypatch.setattr(run_worker, "build_deps", lambda context: deps(provider))
    now = datetime.now(timezone.utc)
    if record:
        store.record_received(engine, EMAIL_KEY, "sender@example.com", now)
    run_id = start_run(engine, "email", now)
    run_worker.handler({"task": "run", "run_id": run_id, "email_key": EMAIL_KEY}, Ctx())
    with Session(engine) as s:
        return s.get(Run, run_id)


def test_email_event_runs_the_run_with_candidates_from_the_email(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    put_email(monkeypatch)
    p = FakeProvider(replies=[roles({}), extract_json(), score_json(90)])
    run = email_run(engine, monkeypatch, p)
    assert run.trigger == "email" and run.finished_at is not None and (run.found, run.matched) == (1, 1)
    with Session(engine) as s:
        assert s.exec(select(Job)).one().origin == "email"
    assert p.replies == []


def test_inbound_row_is_marked_done_after_a_good_run(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    put_email(monkeypatch)
    email_run(engine, monkeypatch, FakeProvider(replies=[roles({}), extract_json(), score_json(90)]))
    assert store.get_by_key(engine, EMAIL_KEY).status == store.DONE


def test_unreadable_email_object_fails_the_run_clearly_and_marks_the_row_failed(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    boto3.client("s3").create_bucket(Bucket="inbox")
    monkeypatch.setenv("JOBMECLOUD_INBOX_BUCKET", "inbox")  # nothing stored under the key
    run = email_run(engine, monkeypatch, FakeProvider())
    assert run.finished_at is not None and any("could not be read" in e for e in run.errors)
    row = store.get_by_key(engine, EMAIL_KEY)
    assert row.status == store.FAILED and "could not be read" in row.note
    assert not run_lock_held(engine, datetime.now(timezone.utc))


def test_dropped_roles_are_summarised_in_the_run_errors(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    put_email(monkeypatch)
    p = FakeProvider(replies=[roles({}, {"url": "", "employer": "Contoso", "title": "Lead"}), extract_json(), score_json(90)])
    run = email_run(engine, monkeypatch, p)
    assert run.found == 1 and any("1 recommended role had no usable link" in e for e in run.errors)


def test_failed_setup_check_closes_the_run_gives_the_lock_back_and_marks_the_row_failed(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    save_search(data_dir, SearchProfile(target_roles=[]))
    put_email(monkeypatch)
    run = email_run(engine, monkeypatch, FakeProvider())
    assert run.finished_at is not None and run.errors == ["Add at least one job title in What you're looking for."]
    assert store.get_by_key(engine, EMAIL_KEY).status == store.FAILED
    assert not run_lock_held(engine, datetime.now(timezone.utc))


def test_lock_is_released_after_a_good_email_run(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    put_email(monkeypatch)
    email_run(engine, monkeypatch, FakeProvider(replies=[roles({}), extract_json(), score_json(90)]))
    assert not run_lock_held(engine, datetime.now(timezone.utc))


def test_email_run_without_a_recorded_row_still_works(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    put_email(monkeypatch)
    run = email_run(engine, monkeypatch, FakeProvider(replies=[roles({}), extract_json(), score_json(90)]), record=False)
    assert run.found == 1 and store.get_by_key(engine, EMAIL_KEY) is None


def test_a_report_with_nothing_recommended_finishes_with_a_clear_note(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    put_email(monkeypatch)
    run = email_run(engine, monkeypatch, FakeProvider(replies=[roles({"verdict": "applied"}, {"verdict": "not_new", "url": "https://a.example/2"})]))
    assert run.found == 0 and run.finished_at is not None
    assert any("2 roles" in e and "none were" in e for e in run.errors)
    assert store.get_by_key(engine, EMAIL_KEY).status == store.DONE


def test_an_empty_report_says_it_named_no_roles(data_dir, engine, monkeypatch):
    setup_profile(data_dir)
    put_email(monkeypatch)
    run = email_run(engine, monkeypatch, FakeProvider(replies=[roles()]))
    assert run.found == 0 and any("no roles" in e for e in run.errors)
