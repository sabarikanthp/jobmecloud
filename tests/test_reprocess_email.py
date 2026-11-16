from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import boto3
import pytest
from inbound_fixtures import make_email
from sqlalchemy import text

from jobmecloud.admin.stack import ingest_settings
from jobmecloud.inbound import store
from jobmecloud.inbound.replay import ReplayRefused, reprocess_email
from jobmecloud.inbound.trust import TrustConfig

NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
CONFIG = TrustConfig(address="reports@mail.example.com", sender="sender@example.com")
BUCKET, KEY = "inbox", "inbound/one"


class Recording:
    def __init__(self):
        self.started = []

    def start_run(self, run_id, email_key=None):
        self.started.append((run_id, email_key))


@pytest.fixture
def s3():
    client = boto3.client("s3")
    client.create_bucket(Bucket=BUCKET)
    client.put_object(Bucket=BUCKET, Key=KEY, Body=make_email())
    return client


def replay(engine, s3, d, **kwargs):
    return reprocess_email(engine, s3, d, bucket=BUCKET, key=KEY, config=CONFIG, daily_limit=5, now=NOW, **kwargs)


def free_the_lock(engine):
    with engine.begin() as c:
        c.execute(text("delete from runlock"))


def test_reprocess_restarts_a_waiting_email_and_refuses_a_done_one_without_force(engine, s3):
    email_id = store.record_received(engine, KEY, "sender@example.com", NOW)
    store.set_status(engine, email_id, store.WAITING)
    d = Recording()
    assert replay(engine, s3, d) == store.STARTED and len(d.started) == 1
    free_the_lock(engine)
    store.set_status(engine, email_id, store.DONE)
    with pytest.raises(ReplayRefused, match="--force"):
        replay(engine, s3, d)
    assert len(d.started) == 1
    assert replay(engine, s3, d, force=True) == store.STARTED and len(d.started) == 2


def test_an_email_that_was_never_recorded_can_be_run_by_key(engine, s3):
    d = Recording()
    assert replay(engine, s3, d) == store.STARTED and len(d.started) == 1


def test_recent_lists_the_newest_emails_first(engine):
    for i in range(3):
        store.record_received(engine, f"inbound/{i}", None, NOW + timedelta(minutes=i))
    rows = store.recent(engine, limit=2)
    assert [r.s3_key for r in rows] == ["inbound/2", "inbound/1"]


def test_ingest_settings_are_read_from_the_ingest_functions_environment():
    cfn, lam = MagicMock(), MagicMock()
    cfn.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": [
        {"ResourceType": "AWS::Lambda::Function", "LogicalResourceId": "ApiFunctionABC", "PhysicalResourceId": "api-fn"},
        {"ResourceType": "AWS::Lambda::Function", "LogicalResourceId": "InboundIngestFunctionXYZ", "PhysicalResourceId": "ingest-fn"},
    ]}]
    lam.get_function_configuration.return_value = {"Environment": {"Variables": {
        "JOBMECLOUD_INBOUND_ADDRESS": "reports@mail.example.com", "JOBMECLOUD_INBOUND_SENDER": "sender@example.com",
        "JOBMECLOUD_INBOUND_DAILY_LIMIT": "7", "JOBMECLOUD_RUN_FUNCTION": "run-fn"}}}
    got = ingest_settings("JobMeCloud", cfn=cfn, lam=lam)
    lam.get_function_configuration.assert_called_once_with(FunctionName="ingest-fn")
    assert got == {"address": "reports@mail.example.com", "sender": "sender@example.com", "daily_limit": 7,
                   "run_function": "run-fn"}
