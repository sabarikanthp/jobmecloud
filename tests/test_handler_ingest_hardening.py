import inspect
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from inbound_fixtures import make_email

from jobmecloud.inbound import service, store
from jobmecloud.inbound.service import MAX_RAW_BYTES, handle_email
from jobmecloud.inbound.trust import TrustConfig

NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
CONFIG = TrustConfig(address="reports@mail.example.com", sender="sender@example.com")
BUCKET = "inbox"


class Recording:
    def __init__(self):
        self.started = []

    def start_run(self, run_id, email_key=None):
        self.started.append((run_id, email_key))


class Spy:
    """Wraps a real S3 client and counts how often the body is read."""

    def __init__(self, client):
        self.client, self.gets = client, 0

    def head_object(self, **kwargs):
        return self.client.head_object(**kwargs)

    def get_object(self, **kwargs):
        self.gets += 1
        return self.client.get_object(**kwargs)


@pytest.fixture
def s3():
    client = boto3.client("s3")
    client.create_bucket(Bucket=BUCKET)
    return client


def put(s3, key="inbound/one", body=None, **kwargs):
    s3.put_object(Bucket=BUCKET, Key=key, Body=body if body is not None else make_email(**kwargs))
    return key


def handle(engine, s3, key, d=None, **kwargs):
    kwargs.setdefault("now", NOW)
    return handle_email(engine, s3, d or Recording(), bucket=BUCKET, key=key, config=CONFIG, daily_limit=5,
                        sleep=lambda seconds: None, **kwargs)


def test_an_email_the_parser_cannot_read_is_recorded_failed_not_lost(engine, s3, monkeypatch):
    key = put(s3)

    def boom(raw):
        raise ValueError("cannot parse")

    monkeypatch.setattr(service, "parse_email", boom)
    d = Recording()
    assert handle(engine, s3, key, d) == store.FAILED
    row = store.get_by_key(engine, key)
    assert row.status == store.FAILED and "could not be read" in row.note and d.started == []


def test_the_email_is_recorded_before_anything_is_parsed(engine, s3, monkeypatch):
    key = put(s3)
    seen = {}

    def spy(raw):
        seen["row"] = store.get_by_key(engine, key)
        raise ValueError("stop here")

    monkeypatch.setattr(service, "parse_email", spy)
    handle(engine, s3, key)
    assert seen["row"] is not None  # a crash during parsing still leaves a record


def test_a_second_delivery_while_the_first_is_working_does_nothing(engine, s3):
    key = put(s3)
    email_id = store.record_received(engine, key, None, NOW)
    assert store.claim(engine, email_id, (store.RECEIVED,), NOW)  # the first invocation is mid-way
    d = Recording()
    assert handle(engine, s3, key, d) == "duplicate" and d.started == []


def test_a_claim_abandoned_by_a_crashed_invocation_is_taken_over(engine, s3):
    key = put(s3)
    email_id = store.record_received(engine, key, None, NOW - timedelta(minutes=30))
    store.claim(engine, email_id, (store.RECEIVED,), NOW - timedelta(minutes=30))
    assert handle(engine, s3, key) == store.STARTED


def test_a_message_over_the_size_limit_is_rejected_without_being_read(engine, s3):
    key = put(s3, "inbound/big", body=b"x" * (MAX_RAW_BYTES + 1))
    spy = Spy(s3)
    assert handle(engine, spy, key) == store.REJECTED
    assert spy.gets == 0
    assert "too large" in store.get_by_key(engine, key).note


def test_the_lock_wait_covers_a_documents_job():
    assert inspect.signature(handle_email).parameters["lock_wait_seconds"].default >= 300
