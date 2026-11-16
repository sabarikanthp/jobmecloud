import json

import pytest
from fakes import FakeProvider, add_job, score_json, setup_profile
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from jobmecloud.api.app import create_app
from jobmecloud.config.profile import SearchProfile, save_search
from jobmecloud.config.settings import ProviderConfig, StepModel, load_settings, save_settings
from jobmecloud.db.models import ActivityLog, Job
from jobmecloud.jobs.check import model_choices
from jobmecloud.llm.errors import ProviderAuthError


def two_providers(data_dir, **steps):
    """A second connected AI, with the given steps (e.g. tailor="other:big") pointed at it."""
    s = load_settings(data_dir)
    s.providers.append(ProviderConfig(id="other", kind="openai_compatible", label="Other"))
    for step, ref in steps.items():
        pid, model = ref.split(":")
        s.steps[step] = StepModel(provider_id=pid, model=model)
    save_settings(data_dir, s)


def make(data_dir, providers=None, **extra):
    setup_profile(data_dir)
    save_search(data_dir, SearchProfile(target_roles=["Data Engineer"], min_base_pay=150000, work_modes=["remote"],
                                      deal_breakers=["Clearance"]))
    providers = providers or {"fake": FakeProvider(replies=[score_json(82)])}
    app = create_app(data_dir, provider_builder=lambda cfg: providers[cfg.id])
    app.state.providers = providers
    return app


@pytest.fixture
def app(data_dir):
    return make(data_dir)


def fit(app, job_id, model="score"):
    return TestClient(app).post(f"/api/jobs/{job_id}/fit", json={"model": model})


def stored(app, job_id):
    with Session(app.state.engine) as s:
        return s.get(Job, job_id)


def test_choices_list_the_distinct_models_with_the_scoring_model_first_and_default(data_dir):
    app = make(data_dir)
    two_providers(data_dir, tailor="other:big", search="other:big")
    r = TestClient(app).get("/api/jobs/check/models")
    assert r.status_code == 200
    choices = r.json()["choices"]
    assert [c["default"] for c in choices] == [True, False]
    assert choices[0]["id"] == "score" and "m" in choices[0]["label"]
    assert "big" in choices[1]["label"] and "Other" in choices[1]["label"]


def test_steps_sharing_a_model_appear_once(data_dir):
    app = make(data_dir)
    choices = TestClient(app).get("/api/jobs/check/models").json()["choices"]
    assert len(choices) == 1 and choices[0]["id"] == "score" and choices[0]["default"] is True


def test_model_choices_with_nothing_connected_is_empty():
    from jobmecloud.config.settings import Settings
    assert model_choices(Settings()) == []


def test_fit_saves_score_reasons_gaps_warnings_and_rule_results(data_dir):
    reply = json.dumps({"score": 82, "deal_breakers": [{"rule": "Clearance", "passed": False, "note": "Needs one"}],
                        "warnings": ["Travel 50%"], "reasons": "Strong match", "gaps": "No Spark"})
    app = make(data_dir, {"fake": FakeProvider(replies=[reply])})
    job = add_job(app.state.engine, pay_min=80000, pay_max=100000, work_mode="remote")
    body = fit(app, job).json()
    fitted = body["fit"]
    assert (fitted["score"], fitted["reasons"], fitted["gaps"]) == (82, "Strong match", "No Spark")
    assert fitted["warnings"] == ["Travel 50%"]
    failed = {r["rule"] for r in fitted["rules"] if not r["passed"]}
    assert failed == {"Minimum pay", "Clearance"}
    saved = stored(app, job)
    assert (saved.match_score, saved.reasons, saved.gaps) == (82, "Strong match", "No Spark")
    assert "Travel 50%" in saved.flags and {r["rule"] for r in saved.hard_rules} >= {"Minimum pay", "Clearance"}
    assert body["job"]["match_score"] == 82 and body["job"]["status"] == "New"
    assert "Applied" in body["job"]["allowed_next"]


def test_fit_reports_the_cutoff_and_whether_the_score_clears_it(data_dir):
    app = make(data_dir, {"fake": FakeProvider(replies=[score_json(74), score_json(75)])})
    job = add_job(app.state.engine)
    low = fit(app, job).json()["fit"]
    high = fit(app, job).json()["fit"]
    assert (low["cutoff"], low["above_cutoff"]) == (75, False)
    assert (high["cutoff"], high["above_cutoff"]) == (75, True)


def test_the_chosen_models_provider_and_model_are_the_ones_called(data_dir):
    default, other = FakeProvider(replies=[score_json(60)]), FakeProvider(replies=[score_json(90)])
    app = make(data_dir, {"fake": default, "other": other})
    two_providers(data_dir, tailor="other:big")
    job = add_job(app.state.engine)
    r = fit(app, job, "tailor")
    assert r.status_code == 200 and r.json()["fit"]["score"] == 90 and r.json()["fit"]["model"] == "big"
    assert default.calls == [] and other.calls[0]["model"] == "big"


def test_fit_logs_an_entry_naming_the_model_and_cost(app):
    job = add_job(app.state.engine)
    fit(app, job)
    with Session(app.state.engine) as s:
        [entry] = s.exec(select(ActivityLog).where(ActivityLog.job_id == job)).all()
    assert entry.action == "fit_checked" and "m" in entry.note and "about $" in entry.note


def test_a_recheck_overwrites_without_piling_up_flags_or_rules(data_dir):
    app = make(data_dir, {"fake": FakeProvider(replies=[score_json(70, failed=True), score_json(88)])})
    job = add_job(app.state.engine, pay_min=None, pay_max=None)
    fit(app, job)
    first = stored(app, job)
    assert any(not r["passed"] for r in first.hard_rules)
    fit(app, job)
    second = stored(app, job)
    assert second.match_score == 88
    assert not any(r["rule"] == "Clearance" for r in second.hard_rules)
    assert second.flags.count("Pay unverified") == 1
    assert len(second.hard_rules) == len({r["rule"] for r in second.hard_rules})


def test_a_failed_fit_leaves_the_job_and_any_earlier_fit_untouched(data_dir):
    app = make(data_dir, {"fake": FakeProvider(replies=[score_json(77), ProviderAuthError("bad key")])})
    job = add_job(app.state.engine)
    fit(app, job)
    before = stored(app, job).model_dump()
    r = fit(app, job)
    assert r.status_code == 502 and "key was rejected" in r.json()["detail"]
    assert stored(app, job).model_dump() == before
    with Session(app.state.engine) as s:
        assert len(s.exec(select(ActivityLog).where(ActivityLog.job_id == job)).all()) == 1


def test_an_unknown_model_choice_is_refused(app):
    job = add_job(app.state.engine)
    r = fit(app, job, "nonsense")
    assert r.status_code == 400 and app.state.providers["fake"].calls == []


def test_an_unknown_job_is_404(app):
    assert fit(app, 99999).status_code == 404


def test_a_job_with_no_description_cannot_be_judged_and_says_so(app):
    job = add_job(app.state.engine, description=None)
    r = fit(app, job)
    assert r.status_code == 422 and "description" in r.json()["detail"].lower()
    assert app.state.providers["fake"].calls == []


def test_fit_works_without_a_resume(app):
    job = add_job(app.state.engine)
    assert fit(app, job).status_code == 200
    prompt = app.state.providers["fake"].calls[0]["messages"][0]["content"]
    assert "Northwind Labs" in prompt


def test_provider_not_configured_gives_the_plain_message(data_dir):
    app = make(data_dir)
    s = load_settings(data_dir)
    s.steps = {}
    save_settings(data_dir, s)
    job = add_job(app.state.engine)
    r = fit(app, job)
    assert r.status_code == 400 and r.json()["detail"] == "Connect an AI first."
