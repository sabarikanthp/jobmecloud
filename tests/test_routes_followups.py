from datetime import date, datetime, timezone

from sqlmodel import Session

from jobmecloud.db.models import Job

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def _job(client) -> int:
    with Session(client.app.state.engine) as s:
        j = Job(employer="Northwind Labs", title="Data Engineer", origin="scout", status="Applied",
                first_seen_at=NOW)
        s.add(j)
        s.commit()
        return j.id


def test_followup_flow(client):
    client.app.state.today = lambda: date(2026, 11, 12)
    jid = _job(client)
    r = client.post("/api/followups", json={"type": "Thank-you note", "due_date": "2026-11-11", "job_id": jid})
    assert r.status_code == 201
    row = r.json()
    assert (row["bucket"], row["employer"], row["job_title"], row["due_date"]) == \
           ("overdue", "Northwind Labs", "Data Engineer", "2026-11-11")
    client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-20", "job_id": jid})
    assert [x["bucket"] for x in client.get("/api/followups").json()] == ["overdue", "upcoming"]
    assert len(client.get("/api/followups?bucket=overdue").json()) == 1
    assert len(client.get(f"/api/followups?job_id={jid}").json()) == 2
    s = client.post(f"/api/followups/{row['id']}/snooze", json={"until": "2026-11-15"}).json()
    assert (s["status"], s["bucket"]) == ("Snoozed", "upcoming")
    d = client.post(f"/api/followups/{row['id']}/done", json={"outcome_note": "Sent"}).json()
    assert (d["status"], d["bucket"], d["outcome_note"], d["completed_date"]) == ("Done", "done", "Sent", datetime.now().astimezone().date().isoformat())
    assert [x["id"] for x in client.get("/api/followups?bucket=done").json()] == [row["id"]]


def test_done_can_schedule_the_next_follow_up(client):
    client.app.state.today = lambda: date(2026, 11, 12)
    jid = _job(client)
    fu = client.post("/api/followups", json={"type": "Recruiter outreach", "due_date": "2026-11-12",
                                              "job_id": jid, "note": "Ping about timing"}).json()
    d = client.post(f"/api/followups/{fu['id']}/done", json={"outcome_note": "Sent", "next_date": "2026-11-19"})
    assert d.status_code == 200 and d.json()["status"] == "Done"
    rows = client.get(f"/api/followups?job_id={jid}").json()
    nxt = [r for r in rows if r["id"] != fu["id"]]
    assert [(r["type"], r["due_date"], r["status"], r["note"], r["bucket"]) for r in nxt] == \
           [("Recruiter outreach", "2026-11-19", "Open", "Ping about timing", "upcoming")]


def test_done_with_a_past_next_date_changes_nothing(client):
    client.app.state.today = lambda: date(2026, 11, 12)
    jid = _job(client)
    fu = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-12", "job_id": jid}).json()
    r = client.post(f"/api/followups/{fu['id']}/done", json={"next_date": "2026-11-01"})
    assert r.status_code == 400
    rows = client.get(f"/api/followups?job_id={jid}").json()
    assert [(x["id"], x["status"]) for x in rows] == [(fu["id"], "Open")]


def test_errors(client):
    client.app.state.today = lambda: date(2026, 11, 12)
    jid = _job(client)
    assert client.post("/api/followups/999/cancel").json() == {"detail": "No follow-up with that id"}
    assert client.post("/api/followups/999/cancel").status_code == 404
    r = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-12"})
    assert (r.status_code, r.json()["detail"]) == (400, "A follow-up needs a job or a contact.")
    fu = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-12", "job_id": jid}).json()
    r = client.post(f"/api/followups/{fu['id']}/snooze", json={"until": "2026-11-01"})
    assert (r.status_code, r.json()["detail"]) == (400, "Pick today or a later date.")
    assert client.post(f"/api/followups/{fu['id']}/reschedule", json={"due_date": "2026-11-14"}).json()["due_date"] == "2026-11-14"
    client.post(f"/api/followups/{fu['id']}/cancel")
    r = client.post(f"/api/followups/{fu['id']}/cancel")
    assert (r.status_code, r.json()["detail"]) == (400, "That follow-up is already finished.")


def test_unknown_job_or_contact_is_a_400(client):
    r = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-12", "job_id": 9999})
    assert (r.status_code, r.json()["detail"]) == (400, "That job no longer exists.")
    r = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-12", "contact_id": 9999})
    assert (r.status_code, r.json()["detail"]) == (400, "That contact no longer exists.")
    assert client.get("/api/followups").json() == []


def test_completed_date_is_the_local_day(client, monkeypatch):
    from datetime import timedelta
    from jobmecloud.jobs import tracking
    monkeypatch.setattr(tracking, "_local_tz", lambda: timezone(timedelta(hours=-8)))
    monkeypatch.setattr("jobmecloud.api.routes_followups._now", lambda: datetime(2026, 11, 12, 3, tzinfo=timezone.utc))
    jid = _job(client)
    fu = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-12", "job_id": jid}).json()
    d = client.post(f"/api/followups/{fu['id']}/done", json={}).json()
    assert d["completed_date"] == "2026-11-11"


def test_contact_followup_lands_on_the_contacts_job(client):
    jid = _job(client)
    cid = client.post("/api/contacts", json={"name": "Jordan Example", "job_id": jid}).json()["id"]
    fu = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-20", "contact_id": cid}).json()
    assert fu["job_id"] == jid and fu["contact_id"] == cid
    detail = client.get(f"/api/jobs/{jid}").json()
    assert [f["id"] for f in detail["followups"]] == [fu["id"]]
    rows = client.get("/api/jobs?has_followup=true").json()["rows"]
    assert [(r["id"], r["next_followup_due"]) for r in rows] == [(jid, "2026-11-20")]
