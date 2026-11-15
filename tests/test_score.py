import json

from jobmecloud.agents.jobscout.extract import Posting
from jobmecloud.agents.jobscout.rules import RuleResult
from jobmecloud.agents.jobscout.score import RUBRIC, score_job
from jobmecloud.config.profile import SearchProfile
from jobmecloud.llm.pricing import CostTracker
from fakes import FakeProvider


def post(**kw):
    base = dict(employer="Contoso Health, Inc.", title="Data Engineer", requisition_id=None, location=None,
                work_mode=None, pay_min=None, pay_max=None, posted_date=None, apply_url="https://c.example",
                description="d")
    return Posting(**{**base, **kw})


def test_score_job_clamps_and_maps():
    reply = json.dumps({"score": 130, "deal_breakers": [{"rule": "Requires security clearance", "passed": False, "note": "Needs TS"}],
                        "warnings": ["Onsite rules unclear"], "reasons": "Good fit", "gaps": "No Spark"})
    prof = SearchProfile(deal_breakers=["Requires security clearance"], warnings=["Onsite rules unclear"], do_not_claim=["Spark"])
    p = FakeProvider(replies=[reply])
    s = score_job(p, "m", post(), prof, None, CostTracker({}, 0))
    assert s.score == 100 and s.deal_breakers == [RuleResult("Requires security clearance", False, "Needs TS")]
    assert (s.warnings, s.reasons, s.gaps) == (["Onsite rules unclear"], "Good fit", "No Spark")
    prompt = p.calls[0]["messages"][0]["content"]
    for text in [RUBRIC, "Requires security clearance", "Onsite rules unclear", "Spark", "Data Engineer"]:
        assert text in prompt


def _score_of(raw):
    reply = json.dumps({"score": raw, "deal_breakers": [], "warnings": [], "reasons": "", "gaps": ""})
    return score_job(FakeProvider(replies=[reply]), "m", post(), SearchProfile(), None, CostTracker({}, 0)).score


def test_score_accepts_whole_number_floats_and_clamps():
    # The schema check already rejects fractions, bools and strings; 85.0 passes it as an integer.
    assert [_score_of(v) for v in (85, 85.0, -3.0, 130.0)] == [85, 85, 0, 100]
    assert type(_score_of(85.0)) is int


def test_score_keeps_only_profile_deal_breakers():
    reply = json.dumps({"score": 70, "warnings": [], "reasons": "", "gaps": "", "deal_breakers": [
        {"rule": "  requires   SECURITY clearance ", "passed": False, "note": "Needs TS"},
        {"rule": "Must love cats", "passed": False, "note": "Invented"},
        {"rule": "Requires security clearance", "passed": True, "note": "Repeat"},
    ]})
    prof = SearchProfile(deal_breakers=["Requires security clearance"])
    s = score_job(FakeProvider(replies=[reply]), "m", post(), prof, None, CostTracker({}, 0))
    assert s.deal_breakers == [RuleResult("Requires security clearance", False, "Needs TS")]
