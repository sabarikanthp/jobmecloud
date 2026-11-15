from datetime import date, datetime, timezone

from sqlmodel import Session, select

from jobmecloud.db.models import ActivityLog, FollowUp, Job

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def _job(client, status="Applied", employer="Northwind Labs") -> int:
    with Session(client.app.state.engine) as s:
        j = Job(employer=employer, title="Data Engineer", origin="scout", status=status,
                first_seen_at=NOW, applied_at=NOW if status == "Applied" else None)
        s.add(j)
        s.commit()
        return j.id


def _log(client, entity_type):
    with Session(client.app.state.engine) as s:
        return [(r.action, r.job_id, r.from_value, r.to_value)
                for r in s.exec(select(ActivityLog).where(ActivityLog.entity_type == entity_type)
                                .order_by(ActivityLog.id))]


def test_contact_crud_and_filter(client):
    jid = _job(client)
    r = client.post("/api/contacts", json={"name": "Jordan Example", "job_id": jid, "relationship": "Recruiter"})
    assert r.status_code == 201
    row = r.json()
    assert (row["employer"], row["job_title"], row["open_followups"]) == ("Northwind Labs", "Data Engineer", 0)
    other = client.post("/api/contacts", json={"name": "Sam Example", "employer": "Contoso Health"}).json()
    assert other["job_id"] is None
    assert [c["id"] for c in client.get("/api/contacts").json()] == [other["id"], row["id"]]
    assert [c["id"] for c in client.get(f"/api/contacts?job_id={jid}").json()] == [row["id"]]
    assert [c["id"] for c in client.get("/api/contacts?q=contoso").json()] == [other["id"]]
    u = client.put(f"/api/contacts/{row['id']}", json={"name": "Jordan Example", "job_id": jid,
                                                       "status": "Contacted"}).json()
    assert u["status"] == "Contacted"
    assert _log(client, "contact") == [("contact_added", jid, None, None),
                                       ("contact_added", None, None, None),
                                       ("contact_updated", jid, None, "Contacted")]


def test_contact_validation(client):
    r = client.post("/api/contacts", json={"name": "  "})
    assert (r.status_code, r.json()["detail"]) == (400, "Please enter the contact's name.")
    r = client.post("/api/contacts", json={"name": "A", "relationship": "Friend"})
    assert r.status_code == 400 and "Recruiter" in r.json()["detail"]
    r = client.post("/api/contacts", json={"name": "A", "status": "Nope"})
    assert r.status_code == 400 and "To contact" in r.json()["detail"]
    r = client.post("/api/contacts", json={"name": "A", "link": "linkedin.com/in/x"})
    assert (r.status_code, r.json()["detail"]) == (400, "The link should start with https://")
    r = client.post("/api/contacts", json={"name": "A", "job_id": 999})
    assert (r.status_code, r.json()["detail"]) == (404, "No job with that id")
    assert client.put("/api/contacts/999", json={"name": "A"}).json() == {"detail": "No contact with that id"}
    assert client.delete("/api/contacts/999").status_code == 404
    assert client.get("/api/contacts").json() == []


def test_delete_contact_cancels_open_followups(client):
    client.app.state.today = lambda: date(2026, 11, 12)
    jid = _job(client)
    cid = client.post("/api/contacts", json={"name": "Jordan Example", "job_id": jid}).json()["id"]
    a = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-20", "contact_id": cid}).json()
    b = client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-20", "contact_id": cid}).json()
    client.post(f"/api/followups/{b['id']}/done")
    assert client.get("/api/contacts").json()[0]["open_followups"] == 1
    assert client.delete(f"/api/contacts/{cid}").status_code == 204
    with Session(client.app.state.engine) as s:
        fa, fb = s.get(FollowUp, a["id"]), s.get(FollowUp, b["id"])
        assert (fa.status, fa.contact_id, fb.status, fb.contact_id) == ("Cancelled", None, "Done", None)
    assert ("followup_cancelled", jid, "Open", "Cancelled") in _log(client, "followup")
    assert _log(client, "contact")[-1] == ("contact_deleted", jid, None, None)


def test_interview_moves_applied_job(client):
    jid = _job(client)
    r = client.post(f"/api/jobs/{jid}/interviews", json={"date": "2026-11-20T14:30", "stage": "Phone screen"})
    assert r.status_code == 201
    row = r.json()
    assert row["status_changed"] is True and row["job_id"] == jid
    assert datetime.fromisoformat(row["date"].replace("Z", "+00:00")).tzinfo is not None
    with Session(client.app.state.engine) as s:
        j = s.get(Job, jid)
        assert j.status == "Interviewing" and j.first_response_at is not None
    d = client.put(f"/api/interviews/{row['id']}", json={"date": "2026-11-21", "stage": "Onsite"}).json()
    assert d["stage"] == "Onsite" and d["status_changed"] is False
    assert client.delete(f"/api/interviews/{row['id']}").status_code == 204
    with Session(client.app.state.engine) as s:
        assert s.get(Job, jid).status == "Interviewing"
    assert [x[0] for x in _log(client, "interview")] == ["interview_added", "interview_updated",
                                                          "interview_deleted"]
    assert all(x[1] == jid for x in _log(client, "interview"))


def test_interview_on_new_job_keeps_status_and_errors(client):
    jid = _job(client, status="New")
    r = client.post(f"/api/jobs/{jid}/interviews", json={"stage": "Intro"})
    assert r.status_code == 201 and r.json()["status_changed"] is False and r.json()["date"] is None
    with Session(client.app.state.engine) as s:
        assert s.get(Job, jid).status == "New"
    assert client.post("/api/jobs/999/interviews", json={}).json() == {"detail": "No job with that id"}
    assert client.put("/api/interviews/999", json={}).json() == {"detail": "No interview with that id"}
    assert client.delete("/api/interviews/999").status_code == 404
    r = client.post(f"/api/jobs/{jid}/interviews", json={"date": "soon"})
    assert r.status_code == 400
