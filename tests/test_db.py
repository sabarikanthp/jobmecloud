from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from jobmecloud.db.models import Job, Run, RunJob
from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate


@pytest.fixture
def engine(data_dir):
    e = make_engine(data_dir=data_dir)
    yield e
    e.dispose()


def test_tables_created(engine):
    migrate(engine)
    names = set(inspect(engine).get_table_names())
    assert {"job", "runjob", "interview", "contact", "followup",
            "activitylog", "run", "watchlistemployer"} <= names


def test_job_and_runjob(engine):
    migrate(engine)
    with Session(engine) as s:
        run = Run(trigger="manual", started_at=datetime.now(UTC))
        s.add(run)
        job = Job(employer="Acme", title="Engineer", status="New", origin="scout",
                  flags=["older post"], first_seen_at=datetime.now(UTC))
        s.add(job)
        s.commit()
        s.add(RunJob(run_id=run.id, job_id=job.id, outcome="new"))
        s.commit()
        assert s.exec(select(Job)).one().flags == ["older post"]


def test_wal_mode(engine):
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_foreign_keys_enforced(tmp_path):
    engine = make_engine(data_dir=tmp_path)
    migrate(engine)
    now = datetime(2026, 11, 11, 12, tzinfo=UTC)
    with Session(engine) as s, pytest.raises(IntegrityError):
        s.add(Run(trigger="manual", started_at=now))
        s.commit()
        s.add(RunJob(run_id=1, job_id=999, outcome="new"))
        s.commit()
    engine.dispose()
