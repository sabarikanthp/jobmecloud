from pydantic import ValidationError

from jobmecloud.config.profile import MasterResume, SearchProfile
from jobmecloud.llm.structured import StructuredOutputError, complete_json
from jobmecloud.llm.types import Provider

MAX_CHARS = 60_000


def _obj(props: dict) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _str() -> dict:
    return {"type": "string"}


def _strs() -> dict:
    return {"type": "array", "items": _str()}


RESUME_SCHEMA = _obj({
    "summary": _str(),
    "roles": {"type": "array", "items": _obj({
        "employer": _str(), "title": _str(), "start": _str(), "end": _str(),
        "location": _str(), "bullets": _strs(),
    })},
    "skills": _strs(),
    "education": {"type": "array", "items": _obj({
        "school": _str(), "degree": _str(), "field": _str(), "year": _str(),
    })},
    "certifications": {"type": "array", "items": _obj({
        "name": _str(), "issuer": _str(), "year": _str(),
    })},
})

SEARCH_SCHEMA = _obj({
    "target_roles": _strs(),
    "positioning": _str(),
    "locations": _strs(),
    "radius_miles": {"type": "integer"},
    "work_modes": {"type": "array", "items": {"type": "string", "enum": ["remote", "hybrid", "onsite"]}},
    "min_base_pay": {"type": "integer"},
    "excluded_employers": _strs(),
    "deal_breakers": _strs(),
    "warnings": _strs(),
    "max_commute_miles": {"type": "integer"},
    "max_posted_days": {"type": "integer"},
    "do_not_claim": _strs(),
})

_COMMON_RULES = (
    "Copy facts exactly as written in the document. "
    "Never invent, guess or improve anything. "
    "When something is not in the document, use an empty value: an empty string, an empty list, "
    "or 0 for a number. "
    "Keep dates exactly as written."
)

RESUME_SYSTEM = (
    "You turn the text of a resume into structured data. " + _COMMON_RULES + " "
    "Make one role per job. Copy each bullet verbatim, without rewording or merging."
)

SEARCH_SYSTEM = (
    "You turn a person's job-search notes into structured data. " + _COMMON_RULES + " "
    "Deal-breakers are things that rule a job out. Warnings are things to flag but not rule out. "
    "If the notes say nothing about work modes, list all three: remote, hybrid and onsite."
)

_BAD_ANSWER = "The AI's answer couldn't be used."


def _call(provider: Provider, model: str, system: str, schema: dict, text: str) -> dict:
    prompt = f"Document:\n\n{text[:MAX_CHARS]}"
    data, _usage = complete_json(provider, model=model, system=system, prompt=prompt, schema=schema)
    return data


def draft_resume(provider: Provider, model: str, text: str) -> MasterResume:
    data = _call(provider, model, RESUME_SYSTEM, RESUME_SCHEMA, text)
    try:
        return MasterResume.model_validate(data)
    except ValidationError as e:
        raise StructuredOutputError(_BAD_ANSWER) from e


def draft_search_profile(provider: Provider, model: str, text: str) -> SearchProfile:
    data = _call(provider, model, SEARCH_SYSTEM, SEARCH_SCHEMA, text)
    for key in ("radius_miles", "min_base_pay", "max_commute_miles", "max_posted_days"):
        if not data.get(key):
            data[key] = None
    try:
        return SearchProfile.model_validate(data)
    except ValidationError as e:
        raise StructuredOutputError(_BAD_ANSWER) from e
