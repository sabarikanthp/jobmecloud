from datetime import datetime, timedelta, timezone

from fakes import FakeProvider, deps, extract_json, rec, score_json, setup_profile, tool_reply
from sqlmodel import Session

from jobmecloud.agents.jobscout.pipeline import start_run
from jobmecloud.db.models import Run


def ready_client(client, provider):
    setup_profile(client.app.state.data_dir)
    client.app.state.run_deps = deps(provider)
    return client


def test_run_now_and_results(client):
    p = FakeProvider(replies=[tool_reply(rec("https://northwind.example/1", "Northwind Labs", "Senior Data Engineer")),
                              "done", extract_json(), score_json(90)])
    ready_client(client, p)
    r = client.post("/api/runs")
    assert r.status_code == 202
    client.app.state.run_thread.join(10)
    latest = client.get("/api/runs/latest").json()
    assert latest["running"] is False and (latest["found"], latest["matched"]) == (1, 1)
    rows = client.get(f"/api/runs/{latest['id']}/jobs").json()
    assert rows[0]["outcome"] == "matched" and rows[0]["job"]["match_score"] == 90
    assert rows[0]["job"]["allowed_next"] == ["Applied", "Skipped", "Rejected", "Withdrawn", "Unavailable"]


def test_run_now_errors(client):
    assert client.get("/api/runs/latest").json() is None
    r = client.post("/api/runs")
    assert r.status_code == 400 and r.json()["detail"] == "Connect an AI first."
    ready_client(client, FakeProvider())
    start_run(client.app.state.engine, "manual", datetime.now(timezone.utc))
    r = client.post("/api/runs")
    assert r.status_code == 409 and r.json()["detail"] == "A run is already in progress."
    assert client.get("/api/runs/999/jobs").status_code == 404
    assert client.get("/api/runs/999/jobs").json()["detail"] == "No run with that id"


def test_abandoned_run_not_shown_running(client):
    engine = client.app.state.engine
    with Session(engine) as s:
        s.add(Run(trigger="manual", started_at=datetime.now(timezone.utc) - timedelta(hours=3)))
        s.commit()
    assert client.get("/api/runs/latest").json()["running"] is False


def test_run_now_bad_settings_is_400(client):
    (client.app.state.data_dir / "settings.yaml").write_text("match_cutoff: 500\n", encoding="utf-8")
    r = client.post("/api/runs")
    assert r.status_code == 400 and "settings.yaml" in r.json()["detail"]
    assert client.app.state.run_thread is None
