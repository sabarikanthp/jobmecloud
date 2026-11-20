from datetime import date

import pytest
from fakes import FakeProvider, add_job, extract_json
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from jobmecloud.db.models import ActivityLog, ApiKey, Contact, FollowUp, Interview, Job
from jobmecloud.mcp import registry
from mcp_helpers import call_tool, failed, make_key, ok
from test_check_job import POSTING_TEXT, make


@pytest.fixture
def key(client):
    return make_key(client, "readwrite", name="Laptop")


def job(client, **kw):
    return add_job(client.app.state.engine, **kw)


def row(client, model, id_):
    with Session(client.app.state.engine) as s:
        return s.get(model, id_)


def actors(client, job_id):
    with Session(client.app.state.engine) as s:
        return {r.actor for r in s.exec(select(ActivityLog).where(ActivityLog.job_id == job_id))}


def test_set_job_status_applied_creates_default_followup_and_logs_actor(client, key):
    jid = job(client)
    out = ok(call_tool(client, key, "set_job_status", job=jid, status="Applied"))
    assert out["status"] == "Applied" and out["follow_up_id"] is not None
    assert "claude:Laptop" in actors(client, jid)


def test_invalid_status_transition_is_tool_error(client, key):
    jid = job(client)
    assert failed(call_tool(client, key, "set_job_status", job=jid, status="Offer"))


def test_set_job_status_skipped_needs_a_reason(client, key):
    jid = job(client)
    failed(call_tool(client, key, "set_job_status", job=jid, status="Skipped"))
    ok(call_tool(client, key, "set_job_status", job=jid, status="Skipped", skip_reason="Not a fit"))
    assert row(client, Job, jid).status == "Skipped"


def test_update_job_sets_notes_and_dates(client, key):
    jid = job(client, status="Applied")
    ok(call_tool(client, key, "update_job", job=jid, notes="hello", applied_date="2026-01-05"))
    j = row(client, Job, jid)
    assert j.notes == "hello" and j.applied_at is not None


def test_append_job_note_keeps_existing_text(client, key):
    jid = job(client, notes="first")
    ok(call_tool(client, key, "append_job_note", job=jid, text="second"))
    notes = row(client, Job, jid).notes
    assert notes.startswith("first\n") and notes.endswith("second")


def test_add_job_creates_manual_job_and_rejects_duplicate(client, key):
    out = ok(call_tool(client, key, "add_job", employer="Acme", title="Staff Engineer", apply_url="https://a.example/1"))
    assert row(client, Job, out["id"]).origin == "manual"
    assert failed(call_tool(client, key, "add_job", employer="Acme", title="Staff Engineer", apply_url="https://a.example/1"))


def test_followup_lifecycle(client, key):
    jid = job(client)
    fu = ok(call_tool(client, key, "create_followup", type="Other", due_date="2099-01-01", job=jid, note="ping"))
    fid = fu["id"]
    ok(call_tool(client, key, "reschedule_followup", id=fid, due_date="2099-02-01"))
    assert row(client, FollowUp, fid).due_date == date(2099, 2, 1)
    ok(call_tool(client, key, "snooze_followup", id=fid, until="2099-03-01"))
    assert row(client, FollowUp, fid).status == "Snoozed"
    done = ok(call_tool(client, key, "complete_followup", id=fid, outcome_note="spoke", next_date="2099-04-01"))
    assert done["status"] == "Done"
    with Session(client.app.state.engine) as s:
        assert len(s.exec(select(FollowUp).where(FollowUp.job_id == jid)).all()) == 2
    other = ok(call_tool(client, key, "create_followup", type="Other", due_date="2099-01-01", job=jid))
    ok(call_tool(client, key, "cancel_followup", id=other["id"]))
    assert row(client, FollowUp, other["id"]).status == "Cancelled"


def test_contact_create_and_partial_update_keeps_other_fields(client, key):
    jid = job(client)
    c = ok(call_tool(client, key, "create_contact", name="Jane Doe", job=jid, role="Recruiter", notes="met at expo"))
    assert row(client, Contact, c["id"]).job_id == jid
    ok(call_tool(client, key, "update_contact", id=c["id"], role="Hiring manager"))
    after = row(client, Contact, c["id"])
    assert after.role == "Hiring manager" and after.name == "Jane Doe" and after.notes == "met at expo"
    assert failed(call_tool(client, key, "update_contact", id=99999, role="x"))


def test_interview_add_and_partial_update(client, key):
    jid = job(client, status="Applied")
    i = ok(call_tool(client, key, "add_interview", job=jid, stage="Phone", date="2026-12-01", notes="screen"))
    assert row(client, Job, jid).status == "Interviewing"
    ok(call_tool(client, key, "update_interview", job=jid, id=i["id"], stage="Onsite"))
    after = row(client, Interview, i["id"])
    assert after.stage == "Onsite" and after.notes == "screen" and after.date is not None
    assert failed(call_tool(client, key, "update_interview", job=jid, id=99999, stage="x"))


def test_check_job_uses_existing_fit_check_and_counts_toward_limit(data_dir):
    with TestClient(make(data_dir)) as c:
        k = make_key(c, "readwrite")
        out = ok(call_tool(c, k, "check_job", input=POSTING_TEXT))
        assert out["job"]["employer"]
        with Session(c.app.state.engine) as s:
            assert s.exec(select(ApiKey)).first().ai_count == 1


def test_re_evaluate_job_calls_description_route(data_dir):
    with TestClient(make(data_dir, replies=[extract_json()])) as c:
        k = make_key(c, "readwrite")
        jid = add_job(c.app.state.engine, description=None, status="New")
        out = ok(call_tool(c, k, "re_evaluate_job", job=jid, description=POSTING_TEXT))
        assert out["job"]["id"] == jid
        with Session(c.app.state.engine) as s:
            assert s.get(Job, jid).description
            assert s.exec(select(ApiKey)).first().ai_count == 1


def test_write_tools_need_readwrite_key(client):
    ro = make_key(client, "read", name="ro")
    jid = job(client)
    assert "read-only" in failed(call_tool(client, ro, "set_job_status", job=jid, status="Applied"))
    assert row(client, Job, jid).status == "New"


def test_no_delete_or_settings_tools_registered(client):
    names = set(registry.TOOLS)
    assert {"set_job_status", "check_job", "add_interview"} <= names
    assert not [n for n in names if any(w in n for w in ("delete", "remove", "setting", "key", "make_docs"))]
    assert all(registry.TOOLS[n].write for n in names if n.startswith(("set_", "update_", "add_", "create_", "complete_", "snooze_", "reschedule_", "cancel_", "append_", "check_", "re_evaluate")))
    assert registry.TOOLS["check_job"].ai_cost and registry.TOOLS["re_evaluate_job"].ai_cost
