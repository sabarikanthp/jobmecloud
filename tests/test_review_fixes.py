"""Behaviour found missing in the stage 1 code review."""

import logging
from datetime import datetime, timedelta, timezone

from fakes import add_job
from sqlmodel import Session

from jobmecloud.db.models import Job, Run
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.redact import install_log_redaction

KEY = "sk-ant-api03-abcdefghijklmnop1234"


class Recording:
    synchronous_docs = False

    def __init__(self):
        self.docs = []

    def start_run(self, run_id):
        pass

    def start_docs(self, job_id, options):
        self.docs.append(job_id)


def set_docs(client, job_id, status, started_ago_minutes):
    with Session(client.app.state.engine) as s:
        job = s.get(Job, job_id)
        job.docs_status = status
        job.docs_started_at = datetime.now(timezone.utc) - timedelta(minutes=started_ago_minutes)
        s.add(job)
        s.commit()


def test_starting_docs_records_when_it_started(client):
    job_id = add_job(client.app.state.engine, status="New", match_score=90)
    client.app.state.dispatcher = Recording()
    assert client.post(f"/api/jobs/{job_id}/docs", json={}).status_code == 202
    with Session(client.app.state.engine) as s:
        assert s.get(Job, job_id).docs_started_at is not None


def test_docs_that_never_finish_are_reported_as_timed_out(client):
    job_id = add_job(client.app.state.engine, status="New")
    set_docs(client, job_id, "generating", started_ago_minutes=10)
    body = client.get(f"/api/jobs/{job_id}/docs/status").json()
    assert body["status"] == "error" and "timed out" in body["error"]
    assert client.get(f"/api/jobs/{job_id}/docs/status").json()["status"] == "error"  # and it stays that way


def test_docs_still_being_written_are_not_reported_as_timed_out(client):
    job_id = add_job(client.app.state.engine, status="New")
    set_docs(client, job_id, "generating", started_ago_minutes=1)
    assert client.get(f"/api/jobs/{job_id}/docs/status").json()["status"] == "generating"


def test_a_run_that_died_is_reported_as_stopped_not_as_searching(client):
    with Session(client.app.state.engine) as s:
        s.add(Run(trigger="manual", started_at=datetime.now(timezone.utc) - timedelta(minutes=30),
                  stage="Searching for jobs"))  # no lock is held: the worker is gone
        s.commit()
    latest = client.get("/api/runs/latest").json()
    assert latest["running"] is False and latest["stage"] is None
    assert latest["errors"] == ["This run stopped unexpectedly. Please start a new one."]


def test_error_messages_hide_api_keys():
    shown = friendly_message(RuntimeError(f"Incorrect API key provided: {KEY}"))
    assert KEY not in shown and "[hidden]" in shown


def test_logs_hide_api_keys_including_in_tracebacks(caplog):
    install_log_redaction()
    log = logging.getLogger("jobmecloud.test")
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError(f"401 for {KEY}")
        except RuntimeError:
            log.exception("Run failed for %s", KEY)
    assert KEY not in caplog.text and "[hidden]" in caplog.text
