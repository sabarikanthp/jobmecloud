"""JobScout step 4: deal-breaker checks and soft flags that code can decide."""

from dataclasses import dataclass
from datetime import date

from jobmecloud.agents.jobscout.extract import Posting
from jobmecloud.config.profile import SearchProfile
from jobmecloud.jobs.dedup import normalize_employer


@dataclass
class RuleResult:
    rule: str
    passed: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {"rule": self.rule, "passed": self.passed, "note": self.note}


def code_rules(posting: Posting, profile: SearchProfile) -> list[RuleResult]:
    results: list[RuleResult] = []
    if profile.excluded_employers:
        employer = normalize_employer(posting.employer)
        excluded = any(normalize_employer(e) == employer for e in profile.excluded_employers)
        results.append(
            RuleResult("Excluded employer", not excluded, "You excluded this employer." if excluded else "")
        )
    minimum = profile.min_base_pay
    if minimum:
        too_low = posting.pay_max is not None and posting.pay_max < minimum
        note = (
            f"Top of range ${posting.pay_max:,} is below your minimum ${minimum:,}." if too_low else ""
        )
        results.append(RuleResult("Minimum pay", not too_low, note))
    if posting.work_mode:
        allowed = posting.work_mode in profile.work_modes
        results.append(RuleResult("Work mode", allowed, "" if allowed else f"This job is {posting.work_mode}."))
    return results


def code_flags(posting: Posting, profile: SearchProfile, today: date) -> list[str]:
    flags: list[str] = []
    if posting.pay_min is None and posting.pay_max is None:
        flags.append("Pay unverified")
    if profile.max_posted_days is not None and posting.posted_date is not None:
        age = (today - posting.posted_date).days
        if age > profile.max_posted_days:
            flags.append(f"Posted {age} days ago")
    return flags
