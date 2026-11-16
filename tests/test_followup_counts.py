from datetime import date, datetime, timezone

from sqlmodel import Session

from jobmecloud.db.models import Job

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
TODAY = date(2026, 11, 12)


def _job(client) -> int:
    with Session(client.app.state.engine) as s:
        j = Job(employer="Northwind Labs", title="Data Engineer", origin="manual", status="New", first_seen_at=NOW)
        s.add(j)
        s.commit()
        return j.id


def _followup(client, job_id: int, due: str) -> int:
    r = client.post("/api/followups", json={"type": "Other", "due_date": due, "job_id": job_id})
    assert r.status_code == 201
    return r.json()["id"]


def _counts(client) -> dict:
    return client.get("/api/followups/counts").json()


def test_counts_are_zero_with_no_followups(client):
    client.app.state.today = lambda: TODAY
    assert _counts(client) == {"overdue": 0, "due_today": 0}


def test_overdue_and_due_today_are_counted_separately(client):
    client.app.state.today = lambda: TODAY
    job = _job(client)
    _followup(client, job, "2026-11-10")
    _followup(client, job, "2026-11-11")
    _followup(client, job, "2026-11-12")
    assert _counts(client) == {"overdue": 2, "due_today": 1}


def test_upcoming_done_and_cancelled_are_not_counted(client):
    client.app.state.today = lambda: TODAY
    job = _job(client)
    _followup(client, job, "2026-11-13")  # tomorrow: not yet
    done = _followup(client, job, "2026-11-09")
    cancelled = _followup(client, job, "2026-11-12")
    client.post(f"/api/followups/{done}/done", json={"outcome_note": "Sent"})
    client.post(f"/api/followups/{cancelled}/cancel", json={})
    assert _counts(client) == {"overdue": 0, "due_today": 0}


def test_a_snoozed_followup_counts_by_its_new_date(client):
    client.app.state.today = lambda: TODAY
    job = _job(client)
    fid = _followup(client, job, "2026-11-10")
    assert _counts(client)["overdue"] == 1
    client.post(f"/api/followups/{fid}/snooze", json={"until": "2026-11-15"})
    assert _counts(client) == {"overdue": 0, "due_today": 0}


def test_the_check_in_made_by_marking_applied_is_not_counted_until_it_is_due(client):
    client.app.state.today = lambda: TODAY
    job = _job(client)
    r = client.post(f"/api/jobs/{job}/status", json={"status": "Applied", "date": "2026-11-12"})
    assert r.status_code == 200 and r.json()["follow_up_id"] is not None
    assert _counts(client) == {"overdue": 0, "due_today": 0}  # due in 7 days
    client.app.state.today = lambda: date(2026, 11, 19)
    assert _counts(client) == {"overdue": 0, "due_today": 1}
    client.app.state.today = lambda: date(2026, 11, 20)
    assert _counts(client) == {"overdue": 1, "due_today": 0}


def test_counts_use_the_apps_own_today(client):
    job = _job(client)
    _followup(client, job, "2026-11-12")
    client.app.state.today = lambda: date(2026, 11, 11)
    assert _counts(client) == {"overdue": 0, "due_today": 0}
    client.app.state.today = lambda: date(2026, 11, 12)
    assert _counts(client) == {"overdue": 0, "due_today": 1}
    client.app.state.today = lambda: date(2026, 11, 13)
    assert _counts(client) == {"overdue": 1, "due_today": 0}
