from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from jobmecloud.db.models import Job, Run, RunJob
from jobmecloud.db.session import add_missing_columns, get_engine, init_db


@pytest.fixture
def engine(data_dir):
    e = get_engine(data_dir)
    yield e
    e.dispose()


def test_tables_created(engine):
    init_db(engine)
    names = set(inspect(engine).get_table_names())
    assert {"job", "runjob", "interview", "contact", "followup",
            "activitylog", "run", "watchlistemployer"} <= names


def test_job_and_runjob(engine):
    init_db(engine)
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


def test_add_missing_columns_upgrades_old_run_table(tmp_path):
    engine = get_engine(tmp_path)
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE run (id INTEGER PRIMARY KEY, trigger VARCHAR NOT NULL, "
                          "started_at DATETIME NOT NULL)")
    init_db(engine)
    with engine.connect() as c:
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(run)")}
    assert {"stage", "found", "errors"} <= cols
    assert add_missing_columns(engine) == []
    engine.dispose()


def test_foreign_keys_enforced(tmp_path):
    engine = get_engine(tmp_path)
    init_db(engine)
    now = datetime(2026, 11, 11, 12, tzinfo=UTC)
    with Session(engine) as s, pytest.raises(IntegrityError):
        s.add(Run(trigger="manual", started_at=now))
        s.commit()
        s.add(RunJob(run_id=1, job_id=999, outcome="new"))
        s.commit()
    engine.dispose()
