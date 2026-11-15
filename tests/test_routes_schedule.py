import boto3
import pytest
from fakes import FakeProvider, deps, setup_profile
from sqlmodel import Session

from jobmecloud.agents.jobscout.pipeline import record_failed_run
from jobmecloud.config.settings import load_settings
from datetime import datetime, timezone


@pytest.fixture(autouse=True)
def scheduler_env(monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_RUN_FUNCTION_ARN", "arn:aws:lambda:us-east-1:123456789012:function:run-worker")
    monkeypatch.setenv("JOBMECLOUD_SCHEDULER_ROLE_ARN", "arn:aws:iam::123456789012:role/scheduler-invoke")
    monkeypatch.setenv("JOBMECLOUD_TIMEZONE", "UTC")


def schedule_names():
    found = boto3.client("scheduler").list_schedules(NamePrefix="jobmecloud-run-")["Schedules"]
    return sorted(s["Name"] for s in found)


def test_status_before_anything_is_turned_on(client):
    body = client.get("/api/schedule").json()
    assert body["supported"] is True and body["enabled"] is False
    assert body["days"] == [] and body["times"] == [] and body["last_run"] is None and body["next_run"] is None
    assert "wake" not in body


def test_turn_on_creates_schedules_and_saves_the_choice(client):
    r = client.post("/api/schedule/on", json={"days": ["mon", "fri"], "times": ["09:00", "17:00"]})
    assert r.status_code == 200 and r.json() == {"enabled": True}
    assert schedule_names() == ["jobmecloud-run-0900", "jobmecloud-run-1700"]
    saved = load_settings(client.app.state.data_dir).schedule
    assert (saved.enabled, saved.days, saved.times) == (True, ["mon", "fri"], ["09:00", "17:00"])
    status = client.get("/api/schedule").json()
    assert status["enabled"] is True and status["days"] == ["mon", "fri"] and status["next_run"]


def test_turn_on_refuses_bad_input_with_a_plain_message(client):
    r = client.post("/api/schedule/on", json={"days": [], "times": ["09:00"]})
    assert r.status_code == 400 and r.json()["detail"] == "Choose at least one day."
    assert schedule_names() == []


def test_turn_off_removes_schedules(client):
    client.post("/api/schedule/on", json={"days": ["mon"], "times": ["09:00"]})
    r = client.post("/api/schedule/off")
    assert r.status_code == 200 and r.json() == {"enabled": False}
    assert schedule_names() == []
    assert load_settings(client.app.state.data_dir).schedule.enabled is False


def test_status_shows_the_last_scheduled_run(client):
    record_failed_run(client.app.state.engine, "schedule", datetime.now(timezone.utc), "Skipped: a run was already in progress.")
    last = client.get("/api/schedule").json()["last_run"]
    assert last["errors"] == ["Skipped: a run was already in progress."] and last["finished_at"]
