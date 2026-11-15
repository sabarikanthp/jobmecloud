"""JobScout step 5: rate how well a job matches the person, with an AI call."""

import math
from dataclasses import dataclass

from jobmecloud.agents.jobscout.extract import Posting
from jobmecloud.agents.jobscout.rules import RuleResult
from jobmecloud.config.profile import MasterResume, SearchProfile
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.structured import complete_json
from jobmecloud.llm.types import Provider

RUBRIC = (
    "90-100: strong on every requirement. 75-89: strong with minor gaps. "
    "50-74: partial match. Under 50: weak match."
)
SCORE_INPUT_CHARS = 15_000


def _str() -> dict:
    return {"type": "string"}


def _obj(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SCORE_SCHEMA = _obj({
    "score": {"type": "integer"},
    "deal_breakers": {
        "type": "array",
        "items": _obj({"rule": _str(), "passed": {"type": "boolean"}, "note": _str()}),
    },
    "warnings": {"type": "array", "items": _str()},
    "reasons": _str(),
    "gaps": _str(),
})

SCORE_SYSTEM = (
    "You compare a job posting with a job seeker's profile and score the match. "
    "Use only facts in the posting and the profile. Be honest about gaps."
)


@dataclass
class Score:
    score: int
    deal_breakers: list[RuleResult]
    warnings: list[str]
    reasons: str
    gaps: str


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "(none)"


def _build_prompt(posting: Posting, profile: SearchProfile, resume: MasterResume | None) -> str:
    parts = [
        f"Scoring rubric:\n{RUBRIC}\nReturn score as a whole number from 0 to 100.",
        "What the person wants:\n"
        f"Target roles: {', '.join(profile.target_roles) or '(not set)'}\n"
        f"Positioning: {profile.positioning or '(not set)'}\n"
        f"Locations: {', '.join(profile.locations) or '(not set)'}\n"
        f"Work modes: {', '.join(profile.work_modes)}",
        "Deal-breakers. Judge every one against the posting and return each one in deal_breakers "
        "with its exact text as rule. Set passed to false when the job breaks it, and explain in note:\n"
        + _bullets(profile.deal_breakers),
        "Warnings. List in warnings only the ones that apply to this job, with their exact text:\n"
        + _bullets(profile.warnings),
        "Skills the person does not have (do not credit the person with these):\n"
        + _bullets(profile.do_not_claim),
    ]
    if resume is not None:
        roles = [f"{r.title} at {r.employer}" for r in resume.roles]
        parts.append(
            f"Resume summary: {resume.summary or '(none)'}\n"
            f"Roles:\n{_bullets(roles)}\n"
            f"Skills: {', '.join(resume.skills) or '(none)'}"
        )
    pay = "not posted"
    if posting.pay_min is not None or posting.pay_max is not None:
        pay = f"{posting.pay_min or '?'} to {posting.pay_max or '?'}"
    parts.append(
        "The job posting:\n"
        f"Employer: {posting.employer}\nTitle: {posting.title}\n"
        f"Location: {posting.location or 'not stated'}\n"
        f"Work mode: {posting.work_mode or 'not stated'}\n"
        f"Pay: {pay}\n"
        f"Posted: {posting.posted_date or 'not stated'}\n"
        f"Description:\n{(posting.description or '')[:SCORE_INPUT_CHARS]}"
    )
    return "\n\n".join(parts)


def _score(raw: object) -> int:
    """A number from 0 to 100; anything that isn't a finite number scores 0."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        return 0
    return max(0, min(100, round(raw)))


def _rule_key(text: str) -> str:
    return " ".join(text.lower().split())


def _deal_breakers(items: list, rules: list[str]) -> list[RuleResult]:
    """Only the person's own deal-breakers (by text), each once, under the person's wording."""
    wanted = {_rule_key(r): r for r in rules}
    out: dict[str, RuleResult] = {}
    for d in items:
        key = _rule_key(str(d.get("rule", "")))
        if key in wanted and key not in out:
            out[key] = RuleResult(wanted[key], bool(d.get("passed")), str(d.get("note", "")))
    return list(out.values())


def score_job(
    provider: Provider,
    model: str,
    posting: Posting,
    profile: SearchProfile,
    resume: MasterResume | None,
    costs: CostTracker,
) -> Score:
    data, usage = complete_json(
        provider,
        model=model,
        system=SCORE_SYSTEM,
        prompt=_build_prompt(posting, profile, resume),
        schema=SCORE_SCHEMA,
    )
    costs.add(model, usage)
    return Score(
        score=_score(data.get("score")),
        deal_breakers=_deal_breakers(data.get("deal_breakers", []), profile.deal_breakers),
        warnings=[str(w) for w in data.get("warnings", [])],
        reasons=str(data.get("reasons", "")),
        gaps=str(data.get("gaps", "")),
    )
