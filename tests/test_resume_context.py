import json

from docx_fixtures import FIXTURE_READING, make_resume_docx
from fakes import NOW, FakeProvider, add_job, draft_json_for_fixture, fixture_mapping, ready_profile
from fastapi.testclient import TestClient

from jobmecloud.api.app import create_app
from jobmecloud.applydocs.make_docs import make_docs
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.resumes.store import add_resume, default_entry, save_reading

CARD = json.dumps({"target_roles": ["Data lead"], "seniority": "Director", "industries": ["Health"],
                   "skills": ["SQL"], "leadership": "20 engineers", "strengths": ["Cut costs 30%"]})


def second(data_dir):
    other = FIXTURE_READING.model_copy(update={"summary": "PLATFORM MIGRATION SPECIALIST summary."})
    return add_resume(data_dir, name="Platform", filename="p.docx", data=make_resume_docx(), reading=other,
                      mapping=fixture_mapping(), make_default=False, now=NOW)


def test_building_context_covers_new_and_changed_resumes_only(data_dir):
    ready_profile(data_dir)
    other = second(data_dir)
    provider = FakeProvider(replies=[CARD, CARD])
    with TestClient(create_app(data_dir, provider_builder=lambda c: provider)) as c:
        assert c.get("/api/resumes/context").json()["pending"] == 2
        assert c.post("/api/resumes/context/build").json()["pending"] == 0
        assert c.post("/api/resumes/context/build").json()["built"] == 0  # nothing changed: no calls
        save_reading(data_dir, other.id, FIXTURE_READING.model_copy(update={"summary": "Changed."}))
        states = {r["name"]: r["state"] for r in c.get("/api/resumes/context").json()["resumes"]}
        assert states == {"Main": "ready", "Platform": "stale"}
        provider.replies = [CARD]
        assert c.post("/api/resumes/context/build").json()["built"] == 1 and len(provider.calls) == 3


def _ready(data_dir):
    ready_profile(data_dir)
    other = second(data_dir)
    p = FakeProvider(replies=[CARD, CARD])
    with TestClient(create_app(data_dir, provider_builder=lambda c: p)) as c:
        c.post("/api/resumes/context/build")
    return other


def _run(data_dir, engine, replies, **kw):
    p = FakeProvider(replies=replies)
    r = make_docs(data_dir, engine, add_job(engine), provider=p, model="m", costs=CostTracker({}, 0),
                  counter=lambda d: 1, now=NOW, **kw)
    return p, r


def test_with_profiles_the_closest_resume_is_picked_and_said_so(data_dir, engine):
    other = _ready(data_dir)
    pick = json.dumps({"best_id": other.id, "reason": "Platform migration work."})
    p, r = _run(data_dir, engine, [pick, draft_json_for_fixture(), '{"problems": []}'])
    assert "PLATFORM MIGRATION SPECIALIST" in p.calls[1]["messages"][0]["content"]
    assert "Started from Platform (best match: Platform migration work)" in r.note
    assert default_entry(data_dir).name == "Main"


def test_a_named_resume_is_used_without_picking_and_a_bad_pick_keeps_the_default(data_dir, engine):
    other = _ready(data_dir)
    p, _ = _run(data_dir, engine, [draft_json_for_fixture(), '{"problems": []}'], resume_id=other.id)
    assert len(p.calls) == 2  # no pick call
    bad = json.dumps({"best_id": "nonsense", "reason": "x"})
    p, r = _run(data_dir, engine, [bad, draft_json_for_fixture(), '{"problems": []}'])
    assert "PLATFORM MIGRATION SPECIALIST" not in p.calls[1]["messages"][0]["content"]
    assert "default was kept" in r.note
