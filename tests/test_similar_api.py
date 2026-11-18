import json

import pytest
from fakes import FakeProvider, add_job, setup_profile
from fastapi.testclient import TestClient

from jobmecloud.api.app import create_app
from jobmecloud.llm.errors import ProviderAuthError

POSTING = ("We are hiring a Director of Software Engineering to lead platform teams. You will own delivery, mentor "
           "technical leads, manage budgets and vendors, and partner with product on the roadmap. " * 6)


def make(data_dir, provider=None):
    setup_profile(data_dir)
    provider = provider or FakeProvider(replies=[])
    app = create_app(data_dir, provider_builder=lambda cfg: provider)
    app.state.provider = provider
    return TestClient(app)


@pytest.fixture
def client(data_dir):
    with make(data_dir) as c:
        yield c


def verdicts(*items):
    return json.dumps({"verdicts": [{"id": i, "same": s, "reason": r} for i, s, r in items]})


def test_similar_lists_candidates_with_their_reasons_and_what_was_decided(client):
    engine = client.app.state.engine
    old = add_job(engine, employer="Umbrella Press", title="Director, Software Engineering", status="Skipped",
                  skip_reason="Pay too low", requisition_id="R-1")
    me = add_job(engine, employer="Umbrella Press", title="Director, Software Engineering", requisition_id="R-2")
    body = client.get(f"/api/jobs/{me}/similar").json()
    [m] = body["matches"]
    assert (m["id"], m["strength"], m["status"]) == (old, "possible", "Skipped")
    assert "repost" in " ".join(m["reasons"]).lower() and m["decided"] == "Skipped: Pay too low"


def test_similar_for_an_unknown_job_is_404(client):
    assert client.get("/api/jobs/99999/similar").status_code == 404


def test_ask_ai_compares_the_job_with_its_candidates_and_returns_verdicts(data_dir):
    c = make(data_dir)
    engine = c.app.state.engine
    old = add_job(engine, employer="Staffing Partner (anonymous company)", title="Director, Engineering",
                  status="Skipped", skip_reason="Not a fit", description=POSTING)
    me = add_job(engine, employer="Umbrella Press", title="Director of Software Engineering", description=POSTING)
    c.app.state.provider.replies = [verdicts((old, "same", "Same responsibilities and wording."))]
    body = c.post(f"/api/jobs/{me}/similar/ask").json()
    [v] = body["verdicts"]
    assert (v["id"], v["same"], v["decided"]) == (old, "same", "Skipped: Not a fit")
    assert v["reason"].startswith("Same responsibilities") and body["model"] and body["cost_usd"] >= 0
    sent = c.app.state.provider.calls[0]
    assert not sent.get("tools") and POSTING[:60] in sent["messages"][0]["content"]


def test_ask_ai_ignores_verdicts_about_jobs_it_was_not_given(data_dir):
    c = make(data_dir)
    engine = c.app.state.engine
    old = add_job(engine, title="Senior Data Engineer II")
    me = add_job(engine)
    c.app.state.provider.replies = [verdicts((old, "unsure", "Might be."), (424242, "same", "Invented."))]
    ids = [v["id"] for v in c.post(f"/api/jobs/{me}/similar/ask").json()["verdicts"]]
    assert ids == [old]


def test_ask_ai_with_nothing_to_compare_makes_no_call(data_dir):
    c = make(data_dir)
    me = add_job(c.app.state.engine, employer="Globex", title="Chef")
    body = c.post(f"/api/jobs/{me}/similar/ask").json()
    assert body["verdicts"] == [] and "nothing" in body["message"].lower()
    assert c.app.state.provider.calls == []


def test_ask_ai_needs_a_description(data_dir):
    c = make(data_dir)
    add_job(c.app.state.engine, description=POSTING)
    me = add_job(c.app.state.engine, description=None)
    r = c.post(f"/api/jobs/{me}/similar/ask")
    assert r.status_code == 422 and "description" in r.json()["detail"].lower()


def test_ask_ai_failures_are_plain_and_change_nothing(data_dir):
    c = make(data_dir, FakeProvider(raises=ProviderAuthError("bad key")))
    engine = c.app.state.engine
    old = add_job(engine, title="Senior Data Engineer II")
    me = add_job(engine)
    r = c.post(f"/api/jobs/{me}/similar/ask")
    assert r.status_code == 502 and "key was rejected" in r.json()["detail"]
    assert c.get(f"/api/jobs/{me}").json()["status"] == "New" and old
