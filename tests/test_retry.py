import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from jobmecloud.db.retry import ConflictRetryMiddleware, is_conflict, retry_on_conflict


class _Orig(Exception):
    def __init__(self, msg, sqlstate=None):
        super().__init__(msg)
        self.sqlstate = sqlstate


def conflict():
    return OperationalError("UPDATE job", {}, _Orig("could not serialize", "40001"))


def test_retries_then_succeeds():
    calls = []

    @retry_on_conflict(attempts=3, base_delay=0)
    def work():
        calls.append(1)
        if len(calls) < 3:
            raise conflict()
        return "ok"

    assert work() == "ok" and len(calls) == 3


def test_gives_up_after_attempts():
    calls = []

    @retry_on_conflict(attempts=2, base_delay=0)
    def work():
        calls.append(1)
        raise conflict()

    with pytest.raises(OperationalError):
        work()
    assert len(calls) == 2


def test_non_conflict_error_not_retried():
    calls = []

    @retry_on_conflict(attempts=5, base_delay=0)
    def work():
        calls.append(1)
        raise OperationalError("SELECT", {}, _Orig("disk full", "53100"))

    with pytest.raises(OperationalError):
        work()
    assert len(calls) == 1


def test_dsql_occ_message_counts_as_conflict():
    assert is_conflict(OperationalError("x", {}, _Orig("change conflicts with another transaction OC000")))
    assert not is_conflict(ValueError("OC000"))


def _app(fail_times):
    app = FastAPI()
    app.add_middleware(ConflictRetryMiddleware, delay=0)
    state = {"posts": 0, "gets": 0}

    @app.post("/echo")
    async def echo(body: dict):
        state["posts"] += 1
        if state["posts"] <= fail_times:
            raise conflict()
        return body

    @app.get("/read")
    def read():
        state["gets"] += 1
        raise conflict()

    return app, state


def test_middleware_retries_post_once_and_replays_body():
    app, state = _app(fail_times=1)
    r = TestClient(app).post("/echo", json={"a": 1})
    assert r.status_code == 200 and r.json() == {"a": 1} and state["posts"] == 2


def test_middleware_answers_409_when_conflict_persists():
    app, state = _app(fail_times=5)
    r = TestClient(app).post("/echo", json={"a": 1})
    assert r.status_code == 409 and r.json() == {"detail": "Please try again."}
    assert state["posts"] == 2


def test_middleware_does_not_retry_reads():
    app, state = _app(fail_times=0)
    r = TestClient(app, raise_server_exceptions=False).get("/read")
    assert r.status_code == 500 and state["gets"] == 1


def test_pipeline_run_update_retries_on_conflict(engine, monkeypatch):
    from datetime import UTC, datetime

    from sqlmodel import Session

    from jobmecloud.agents.jobscout import pipeline
    from jobmecloud.db.models import Run

    with Session(engine) as s:
        run = Run(trigger="manual", started_at=datetime.now(UTC))
        s.add(run)
        s.commit()
        run_id = run.id
    real_commit, calls = Session.commit, {"n": 0}

    def flaky(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise conflict()
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", flaky)
    pipeline._update_run(engine, run_id, found=7)
    monkeypatch.setattr(Session, "commit", real_commit)
    with Session(engine) as s:
        assert s.get(Run, run_id).found == 7
    assert calls["n"] == 2


def test_app_retries_write_conflicts(data_dir):
    from jobmecloud.api.app import create_app

    app = create_app(data_dir)
    assert any(m.cls is ConflictRetryMiddleware for m in app.user_middleware)
