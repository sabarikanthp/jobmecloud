from datetime import date

import pytest
from fakes import add_job

TODAY = date(2026, 11, 12)


@pytest.fixture
def c(client):
    client.app.state.today = lambda: TODAY
    return client


def _make(c, **body):
    r = c.post("/api/job-fields", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_list_patch_delete_flow(c, engine):
    a = _make(c, name="Pay band", type="text")
    b = _make(c, name="Decision", type="choice", choices=["Yes", "No"])
    jid = add_job(engine)
    r = c.put(f"/api/jobs/{jid}/fields", json={"values": {str(b["id"]): "No"}})
    assert r.status_code == 200 and r.json() == {"fields": {str(b["id"]): "No"}}

    listed = c.get("/api/job-fields").json()
    assert [f["name"] for f in listed] == ["Pay band", "Decision"]
    assert [f["used"] for f in listed] == [0, 1]

    r = c.patch(f"/api/job-fields/{a['id']}", json={"name": "Band", "position": 5})
    assert r.status_code == 200 and r.json()["name"] == "Band" and r.json()["position"] == 5

    r = c.delete(f"/api/job-fields/{b['id']}")
    assert r.status_code == 200 and r.json() == {"deleted_values": 1}
    assert [f["name"] for f in c.get("/api/job-fields").json()] == ["Band"]
    assert c.get(f"/api/jobs/{jid}").json()["fields"] == {}


def test_duplicate_name_is_400_with_copy(c):
    _make(c, name="Pay band", type="text")
    r = c.post("/api/job-fields", json={"name": " pay BAND", "type": "text"})
    assert r.status_code == 400
    assert r.json()["detail"] == "You already have a field called pay BAND."


def test_type_cannot_change(c):
    f = _make(c, name="Pay", type="number")
    r = c.patch(f"/api/job-fields/{f['id']}", json={"type": "text"})
    assert r.status_code == 400
    assert r.json()["detail"] == "A field's type can't be changed. Delete it and add a new one."
    assert c.patch(f"/api/job-fields/{f['id']}", json={"type": "number", "name": "Pay 2"}).status_code == 200


def test_values_are_visible_on_the_job_detail(c, engine):
    num = _make(c, name="Pay", type="number")
    jid = add_job(engine)
    c.put(f"/api/jobs/{jid}/fields", json={"values": {str(num["id"]): "95000.0"}})
    assert c.get(f"/api/jobs/{jid}").json()["fields"] == {str(num["id"]): "95000"}


def test_invalid_value_is_400_and_changes_nothing(c, engine):
    num = _make(c, name="Pay", type="number")
    txt = _make(c, name="Note", type="text")
    jid = add_job(engine)
    r = c.put(f"/api/jobs/{jid}/fields", json={"values": {str(txt["id"]): "ok", str(num["id"]): "abc"}})
    assert r.status_code == 400 and r.json()["detail"] == "Enter a number."
    assert c.get(f"/api/jobs/{jid}").json()["fields"] == {}


def test_unknown_field_and_job(c, engine):
    jid = add_job(engine)
    r = c.put(f"/api/jobs/{jid}/fields", json={"values": {"999": "x"}})
    assert r.status_code == 400 and r.json()["detail"] == "That field no longer exists."
    assert c.put("/api/jobs/999/fields", json={"values": {}}).status_code == 404
    assert c.patch("/api/job-fields/999", json={"name": "x"}).status_code == 404
    assert c.delete("/api/job-fields/999").status_code == 404
