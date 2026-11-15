import json

import pytest
from fakes import FakeProvider
from fastapi.testclient import TestClient

from jobmecloud.api.app import create_app
from jobmecloud.config.profile import MasterResume, ResumeRole, load_resume, save_resume
from jobmecloud.llm.errors import ProviderError
from jobmecloud.setup.ai_import import RESUME_SCHEMA, SEARCH_SCHEMA

RESUME_REPLY = json.dumps({
    "summary": "Builds things.",
    "roles": [{"employer": "Northwind Labs", "title": "Engineer", "start": "2020",
               "end": "Present", "location": "", "bullets": ["Shipped X"]}],
    "skills": ["Python"], "education": [], "certifications": [],
})

SEARCH_REPLY = json.dumps({
    "target_roles": ["Data Analyst"], "positioning": "", "locations": ["Austin"],
    "radius_miles": 0, "work_modes": ["remote"], "min_base_pay": 0,
    "excluded_employers": [], "deal_breakers": ["Night shifts"], "warnings": ["Long commute"],
    "max_commute_miles": 25, "max_posted_days": 0, "do_not_claim": [],
})


def make_ai_client(data_dir, provider):
    app = create_app(data_dir, provider_builder=lambda c: provider)
    c = TestClient(app)
    c.__enter__()
    c.put("/api/providers/p1", json={"id": "p1", "kind": "anthropic", "label": "Claude"})
    c.post("/api/steps/defaults", json={"provider_id": "p1", "model": None})
    return c


@pytest.fixture
def ai_client(data_dir):
    provider = FakeProvider(replies=[RESUME_REPLY])
    c = make_ai_client(data_dir, provider)
    c.provider = provider
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def failing_client(data_dir):
    c = make_ai_client(data_dir, FakeProvider(raises=ProviderError("x")))
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def bad_json_client(data_dir):
    c = make_ai_client(data_dir, FakeProvider(native=False, replies=["nope", "still nope"]))
    yield c
    c.__exit__(None, None, None)


def test_resume_schema_is_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(RESUME_SCHEMA)
    walk(SEARCH_SCHEMA)
    assert "rotation" not in SEARCH_SCHEMA["properties"]


def test_provider_failure_keeps_old_resume(failing_client, data_dir):
    save_resume(data_dir, MasterResume(roles=[ResumeRole(employer="Old", title="T")]))
    r = failing_client.post("/api/profile/search/import", files={"file": ("cv.txt", b"text")})
    assert r.status_code == 502 and "{" not in r.json()["detail"]
    assert load_resume(data_dir).roles[0].employer == "Old"


def test_invalid_ai_json_is_plain(bad_json_client):
    r = bad_json_client.post("/api/profile/search/import", files={"file": ("cv.txt", b"text")})
    assert r.status_code == 502
    assert r.json()["detail"] == "The AI's answer couldn't be used. Try again, or fill in the form yourself."


def test_reply_failing_model_validation_is_502(data_dir):
    bad = json.loads(SEARCH_REPLY)
    bad["max_commute_miles"] = -5  # schema allows it, SearchProfile does not
    c = make_ai_client(data_dir, FakeProvider(replies=[json.dumps(bad)]))
    try:
        r = c.post("/api/profile/search/import", files={"file": ("n.md", b"notes")})
    finally:
        c.__exit__(None, None, None)
    assert r.status_code == 502
    assert r.json()["detail"] == "The AI's answer couldn't be used. Try again, or fill in the form yourself."


def test_no_ai_configured(client):
    r = client.post("/api/profile/search/import", files={"file": ("n.md", b"Looking for data roles")})
    assert r.status_code == 400 and r.json()["detail"] == "Connect an AI first."


def test_empty_file_makes_no_ai_call(ai_client):
    r = ai_client.post("/api/profile/search/import", files={"file": ("cv.txt", b"   ")})
    assert r.status_code == 400
    assert ai_client.provider.calls == []


def test_search_zero_becomes_none(data_dir):
    c = make_ai_client(data_dir, FakeProvider(replies=[SEARCH_REPLY]))
    try:
        r = c.post("/api/profile/search/import", files={"file": ("n.md", b"Data roles in Austin")})
    finally:
        c.__exit__(None, None, None)
    body = r.json()
    assert r.status_code == 200
    assert body["min_base_pay"] is None and body["radius_miles"] is None
    assert body["max_posted_days"] is None and body["max_commute_miles"] == 25
    assert body["deal_breakers"] == ["Night shifts"] and body["work_modes"] == ["remote"]
