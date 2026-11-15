from datetime import date

from jobmecloud.agents.jobscout.extract import Posting
from jobmecloud.agents.jobscout.rules import code_flags, code_rules
from jobmecloud.config.profile import SearchProfile


def post(**kw):
    base = dict(employer="Contoso Health, Inc.", title="Data Engineer", requisition_id=None, location=None,
                work_mode=None, pay_min=None, pay_max=None, posted_date=None, apply_url="https://c.example",
                description="d")
    return Posting(**{**base, **kw})


def test_code_rules():
    prof = SearchProfile(excluded_employers=["contoso health"], min_base_pay=150000, work_modes=["remote"])
    rules = {r.rule: r for r in code_rules(post(pay_max=140000, work_mode="onsite"), prof)}
    assert not rules["Excluded employer"].passed and rules["Excluded employer"].note == "You excluded this employer."
    assert rules["Minimum pay"].note == "Top of range $140,000 is below your minimum $150,000."
    assert not rules["Work mode"].passed
    assert rules["Work mode"].note == "This job is onsite."
    assert all(r.passed for r in code_rules(post(employer="Northwind"), prof))
    assert code_rules(post(), SearchProfile()) == []


def test_rule_result_as_dict():
    prof = SearchProfile(excluded_employers=["x"])
    assert code_rules(post(), prof)[0].as_dict() == {"rule": "Excluded employer", "passed": True, "note": ""}


def test_code_flags():
    prof = SearchProfile(max_posted_days=30)
    assert code_flags(post(posted_date=date(2026, 9, 1)), prof, date(2026, 11, 11)) == ["Pay unverified", "Posted 71 days ago"]
    assert code_flags(post(pay_min=1, posted_date=date(2026, 11, 1)), prof, date(2026, 11, 11)) == []
