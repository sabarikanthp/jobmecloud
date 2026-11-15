import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fakes import FakeProvider, add_job, deps, ready_profile, setup_profile
from sqlmodel import Session

from jobmecloud.agents.jobscout.pipeline import start_run
from jobmecloud.db.models import Run
from jobmecloud.jobs.dispatch import LambdaDispatcher


class Recording:
    """Stands in for the Lambda dispatcher: remembers what was started, runs nothing."""

    synchronous_docs = False

    def __init__(self):
        self.runs, self.docs = [], []

    def start_run(self, run_id):
        self.runs.append(run_id)

    def start_docs(self, job_id, options):
        self.docs.append((job_id, options))


def test_lambda_dispatcher_starts_run_worker_without_waiting():
    lam = MagicMock()
    LambdaDispatcher(lam, run_function="run-fn", docs_function="docs-fn").start_run(12)
    kwargs = lam.invoke.call_args.kwargs
    assert kwargs["FunctionName"] == "run-fn" and kwargs["InvocationType"] == "Event"
    assert json.loads(kwargs["Payload"]) == {"task": "run", "run_id": 12}


def test_lambda_dispatcher_starts_docs_worker_with_options():
    lam = MagicMock()
    LambdaDispatcher(lam, run_function="run-fn", docs_function="docs-fn").start_docs(5, {"feedback": "more data"})
    kwargs = lam.invoke.call_args.kwargs
    assert kwargs["FunctionName"] == "docs-fn" and kwargs["InvocationType"] == "Event"
    assert json.loads(kwargs["Payload"]) == {"task": "docs", "job_id": 5, "options": {"feedback": "more data"}}


def test_run_now_dispatches_and_returns_run_id(client):
    setup_profile(client.app.state.data_dir)
    client.app.state.run_deps = deps(FakeProvider())
    client.app.state.dispatcher = Recording()
    r = client.post("/api/runs")
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    assert client.app.state.dispatcher.runs == [run_id]
    with Session(client.app.state.engine) as s:
        assert s.get(Run, run_id).finished_at is None  # started, waiting for the worker


def test_second_run_now_returns_409_in_progress(client):
    setup_profile(client.app.state.data_dir)
    client.app.state.run_deps = deps(FakeProvider())
    client.app.state.dispatcher = Recording()
    assert client.post("/api/runs").status_code == 202
    again = client.post("/api/runs")
    assert again.status_code == 409 and again.json()["detail"] == "A run is already in progress."
    assert len(client.app.state.dispatcher.runs) == 1


def test_make_docs_returns_202_and_dispatches(client):
    ready_profile(client.app.state.data_dir)
    job_id = add_job(client.app.state.engine, status="New", match_score=90)
    client.app.state.dispatcher = Recording()
    r = client.post(f"/api/jobs/{job_id}/docs", json={"feedback": "  lean into data  "})
    assert r.status_code == 202
    assert client.app.state.dispatcher.docs == [(job_id, {"feedback": "lean into data"})]
    assert client.get(f"/api/jobs/{job_id}/docs/status").json()["status"] == "generating"


def test_make_docs_conflicts_while_a_run_holds_the_lock(client):
    ready_profile(client.app.state.data_dir)
    job_id = add_job(client.app.state.engine, status="New", match_score=90)
    client.app.state.dispatcher = Recording()
    start_run(client.app.state.engine, "manual", datetime.now(timezone.utc))
    r = client.post(f"/api/jobs/{job_id}/docs", json={})
    assert r.status_code == 409 and client.app.state.dispatcher.docs == []


def test_make_docs_unknown_job_and_long_feedback_are_refused_before_dispatch(client):
    client.app.state.dispatcher = Recording()
    assert client.post("/api/jobs/999/docs", json={}).status_code == 404
    job_id = add_job(client.app.state.engine, status="New")
    assert client.post(f"/api/jobs/{job_id}/docs", json={"feedback": "x" * 2001}).status_code == 400
    assert client.app.state.dispatcher.docs == []


def test_docs_status_defaults_to_none_and_404s_for_unknown_jobs(client):
    job_id = add_job(client.app.state.engine, status="New")
    assert client.get(f"/api/jobs/{job_id}/docs/status").json()["status"] is None
    assert client.get("/api/jobs/999/docs/status").status_code == 404


class Failing(Recording):
    def start_run(self, run_id):
        raise RuntimeError("Lambda is unavailable")


def test_run_now_that_cannot_reach_the_worker_gives_the_lock_back(client):
    from datetime import datetime, timezone

    from jobmecloud.jobs.runlock import run_lock_held

    setup_profile(client.app.state.data_dir)
    client.app.state.run_deps = deps(FakeProvider())
    client.app.state.dispatcher = Failing()
    r = client.post("/api/runs")
    assert r.status_code == 502
    assert not run_lock_held(client.app.state.engine, datetime.now(timezone.utc))
    latest = client.get("/api/runs/latest").json()
    assert latest["running"] is False and latest["errors"] == ["The run could not be started. Please try again."]
    client.app.state.dispatcher = Recording()
    assert client.post("/api/runs").status_code == 202  # a new run can start straight away
