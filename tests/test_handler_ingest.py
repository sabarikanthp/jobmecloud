from datetime import datetime, timezone
from urllib.parse import quote_plus

import boto3
import pytest
from inbound_fixtures import make_email
from sqlalchemy import text
from sqlmodel import Session, select

from jobmecloud.db.models import Run
from jobmecloud.handlers import ingest
from jobmecloud.inbound import store
from jobmecloud.inbound.service import handle_email
from jobmecloud.inbound.trust import TrustConfig
from jobmecloud.jobs.runlock import acquire_run_lock, release_run_lock, run_lock_held

NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
CONFIG = TrustConfig(address="reports@mail.example.com", sender="sender@example.com")
BUCKET = "inbox"
ENV = {"JOBMECLOUD_INBOUND_ADDRESS": "reports@mail.example.com", "JOBMECLOUD_INBOUND_SENDER": "sender@example.com",
       "JOBMECLOUD_INBOUND_DAILY_LIMIT": "5", "JOBMECLOUD_INBOX_BUCKET": BUCKET, "JOBMECLOUD_RUN_FUNCTION": "run-fn"}


class Recording:
    def __init__(self, fail=None):
        self.started, self.fail = [], fail

    def start_run(self, run_id, email_key=None):
        if self.fail:
            raise self.fail
        self.started.append((run_id, email_key))


@pytest.fixture
def s3():
    client = boto3.client("s3")
    client.create_bucket(Bucket=BUCKET)
    return client


def put(s3, key="inbound/one", **kwargs):
    s3.put_object(Bucket=BUCKET, Key=key, Body=make_email(**kwargs))
    return key


def handle(engine, s3, key, dispatcher=None, **kwargs):
    kwargs.setdefault("daily_limit", 5)
    kwargs.setdefault("now", NOW)
    return handle_email(engine, s3, dispatcher or Recording(), bucket=BUCKET, key=key, config=CONFIG,
                        sleep=lambda seconds: None, **kwargs)


def free_the_lock(engine):
    with engine.begin() as c:
        c.execute(text("delete from runlock"))


def test_good_email_creates_an_email_run_and_starts_the_worker_with_its_key(engine, s3):
    key, d = put(s3), Recording()
    assert handle(engine, s3, key, d) == store.STARTED
    with Session(engine) as s:
        run = s.exec(select(Run)).one()
    assert run.trigger == "email" and d.started == [(run.id, key)]
    row = store.get_by_key(engine, key)
    assert (row.status, row.run_id, row.sender) == (store.STARTED, run.id, "sender@example.com")
    assert run_lock_held(engine, NOW)  # the worker releases it when the run ends


def test_the_same_object_twice_starts_only_one_run(engine, s3):
    key, d = put(s3), Recording()
    handle(engine, s3, key, d)
    assert handle(engine, s3, key, d) == "duplicate"
    assert len(d.started) == 1
    with Session(engine) as s:
        assert len(s.exec(select(Run)).all()) == 1


def test_mail_from_anyone_else_is_ignored_and_deleted(engine, s3):
    key = put(s3, sender="stranger@example.net", auth="amazonses.com; dkim=pass header.d=example.net")
    d = Recording()
    assert handle(engine, s3, key, d) == store.IGNORED
    row = store.get_by_key(engine, key)
    assert row.status == store.IGNORED and row.sender == "stranger@example.net"
    assert d.started == [] and not run_lock_held(engine, NOW)
    with pytest.raises(Exception):  # the stranger's message is gone from the mail bucket
        s3.head_object(Bucket=BUCKET, Key=key)


def test_mail_from_the_allowed_sender_that_fails_a_check_is_kept_and_rejected(engine, s3):
    key = put(s3, auth="amazonses.com; dkim=fail header.d=example.com")  # the right sender, but no valid signature
    d = Recording()
    assert handle(engine, s3, key, d) == store.REJECTED
    row = store.get_by_key(engine, key)
    assert row.status == store.REJECTED and "signature" in row.note
    assert s3.head_object(Bucket=BUCKET, Key=key)  # kept, so a real setup problem can be looked into
    assert d.started == []


def test_over_the_daily_limit_is_recorded_skipped(engine, s3):
    first, second = put(s3, "inbound/1"), put(s3, "inbound/2")
    assert handle(engine, s3, first, daily_limit=1) == store.STARTED
    free_the_lock(engine)  # the first run is over
    assert handle(engine, s3, second, daily_limit=1) == store.SKIPPED
    assert store.get_by_key(engine, second).status == store.SKIPPED


def test_lock_busy_waits_then_records_waiting_and_keeps_the_object(engine, s3):
    key, d = put(s3), Recording()
    acquire_run_lock(engine, NOW)  # a run or documents job is in progress
    sleeps = []
    status = handle_email(engine, s3, d, bucket=BUCKET, key=key, config=CONFIG, daily_limit=5, now=NOW,
                          lock_wait_seconds=10, sleep=sleeps.append)
    assert status == store.WAITING and sleeps == [5, 5] and d.started == []
    assert store.get_by_key(engine, key).status == store.WAITING
    assert s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()  # still there to replay


def test_lock_freed_during_the_wait_lets_the_run_start(engine, s3):
    key, d = put(s3), Recording()
    owner = acquire_run_lock(engine, NOW)
    status = handle_email(engine, s3, d, bucket=BUCKET, key=key, config=CONFIG, daily_limit=5, now=NOW,
                          lock_wait_seconds=60, sleep=lambda seconds: release_run_lock(engine, owner))
    assert status == store.STARTED and len(d.started) == 1


def test_failure_to_start_the_worker_gives_the_lock_back_and_marks_failed(engine, s3):
    key = put(s3)
    assert handle(engine, s3, key, Recording(fail=RuntimeError("no such function"))) == store.FAILED
    assert store.get_by_key(engine, key).status == store.FAILED
    with Session(engine) as s:
        assert s.exec(select(Run)).one().finished_at is not None
    assert not run_lock_held(engine, NOW)


def test_a_missing_object_is_recorded_failed(engine, s3):
    assert handle(engine, s3, "inbound/missing") == store.FAILED
    row = store.get_by_key(engine, "inbound/missing")
    assert row.status == store.FAILED and "could not be read" in row.note


def test_a_crash_after_recording_lets_the_retry_finish_the_job(engine, s3):
    key = put(s3)
    store.record_received(engine, key, None, NOW)  # recorded, then the function died
    assert handle(engine, s3, key) == store.STARTED


def test_waiting_and_failed_emails_are_only_rerun_when_asked(engine, s3):
    key = put(s3)
    acquire_run_lock(engine, NOW)
    handle_email(engine, s3, Recording(), bucket=BUCKET, key=key, config=CONFIG, daily_limit=5, now=NOW,
                 lock_wait_seconds=0, sleep=lambda seconds: None)
    assert store.get_by_key(engine, key).status == store.WAITING
    free_the_lock(engine)
    assert handle(engine, s3, key) == "duplicate"
    assert handle(engine, s3, key, reprocess=(store.WAITING,)) == store.STARTED


def test_s3_event_with_several_records_handles_each(engine, s3, monkeypatch):
    keys = [put(s3, "inbound/a"), put(s3, "inbound/b")]
    d = Recording()
    real = ingest.handle_email

    def release_after_each(*args, **kwargs):  # a started run holds the lock until its worker ends
        status = real(*args, **kwargs)
        free_the_lock(engine)
        return status

    monkeypatch.setattr(ingest, "LambdaDispatcher", lambda: d)
    monkeypatch.setattr(ingest, "handle_email", release_after_each)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": k}}} for k in keys]}
    ingest.handler(event, None)
    assert {k for _, k in d.started} == set(keys)


def test_object_keys_with_special_characters_are_decoded(engine, s3, monkeypatch):
    key = put(s3, "inbound/a b+c")
    d = Recording()
    monkeypatch.setattr(ingest, "LambdaDispatcher", lambda: d)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    ingest.handler({"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": quote_plus(key)}}}]}, None)
    assert d.started and d.started[0][1] == key
