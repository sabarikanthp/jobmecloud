"""Runs only against a real Aurora DSQL cluster: JOBMECLOUD_DB_URL=dsql://<endpoint> pytest -m dsql."""

import os
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate
from jobmecloud.db.models import Job, Run, RunJob

pytestmark = [
    pytest.mark.dsql,
    pytest.mark.skipif(not os.environ.get("JOBMECLOUD_DB_URL"), reason="needs a DSQL cluster"),
]


def test_schema_roundtrip_with_json_and_foreign_key():
    engine = make_engine()
    migrate(engine)
    now = datetime.now(UTC)
    with Session(engine) as s:
        run = Run(trigger="manual", started_at=now)
        job = Job(employer="Acme", title="Engineer", status="New", origin="scout",
                  flags=["older post"], first_seen_at=now)
        s.add(run)
        s.add(job)
        s.commit()
        s.add(RunJob(run_id=run.id, job_id=job.id, outcome="new"))
        s.commit()
        try:
            got = s.exec(select(Job).where(Job.id == job.id)).one()
            assert got.flags == ["older post"] and isinstance(got.id, int)
        finally:  # leave the real database as we found it
            s.rollback()
            for row in s.exec(select(RunJob).where(RunJob.run_id == run.id)):
                s.delete(row)
            s.commit()
            s.delete(s.get(Job, job.id))
            s.delete(s.get(Run, run.id))
            s.commit()


def test_inbound_email_table_works_on_a_real_cluster():
    import uuid

    from jobmecloud.db.models import InboundEmail
    from jobmecloud.inbound import store

    engine = make_engine()
    migrate(engine)
    key = f"inbox/test-{uuid.uuid4().hex}"
    now = datetime.now(UTC)
    try:
        email_id = store.record_received(engine, key, "sender@example.com", now)
        assert isinstance(email_id, int)
        assert store.record_received(engine, key, "sender@example.com", now) is None  # the unique key holds
        store.set_status(engine, email_id, store.WAITING, note="test")
        assert store.get_by_key(engine, key).status == store.WAITING
    finally:  # leave the real database as we found it
        with Session(engine) as s:
            for row in s.exec(select(InboundEmail).where(InboundEmail.s3_key == key)):
                s.delete(row)
            s.commit()
