"""JobScout step 3: read a posting page into structured details."""

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from jobmecloud.agents.jobscout.search_agent import Candidate
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult, is_blocked_host
from jobmecloud.llm.structured import complete_json
from jobmecloud.llm.types import Provider

DESCRIPTION_CHARS = 20_000
EXTRACT_INPUT_CHARS = 30_000


def _str() -> dict:
    return {"type": "string"}


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "employer": _str(),
        "title": _str(),
        "requisition_id": _str(),
        "location": _str(),
        "work_mode": {"type": "string", "enum": ["remote", "hybrid", "onsite", "unknown"]},
        "pay_min": {"type": "integer"},
        "pay_max": {"type": "integer"},
        "posted_date": _str(),
        "apply_url": _str(),
    },
    "required": [
        "employer", "title", "requisition_id", "location", "work_mode",
        "pay_min", "pay_max", "posted_date", "apply_url",
    ],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = (
    "You read job postings and return their details as JSON. "
    "Copy facts as written on the page; never guess. Use an empty string when something is not stated. "
    "pay_min and pay_max are annual base pay in USD, whole dollars. Use 0 when pay is not posted. "
    "Convert hourly pay to annual by multiplying by 2080. "
    "posted_date is the date the job was posted, formatted YYYY-MM-DD, or an empty string if not shown. "
    "work_mode is remote, hybrid, onsite, or unknown. "
    "apply_url is the link to apply, or an empty string if the page does not give one."
)


@dataclass
class Posting:
    employer: str
    title: str
    requisition_id: str | None
    location: str | None
    work_mode: str | None
    pay_min: int | None
    pay_max: int | None
    posted_date: date | None
    apply_url: str
    description: str | None


def posting_from_candidate(c: Candidate) -> Posting:
    return Posting(c.employer, c.title, None, None, None, None, None, None, c.url, None)


def _clean(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _pay(value: object) -> int | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # 120000.0 is a whole number of dollars
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _apply_url(value: object, fallback: str) -> str:
    """The extracted link if it is an absolute http(s) URL on an allowed host, else the fallback."""
    url = _clean(value)
    if url is None:
        return fallback
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return fallback
    if parts.scheme.lower() not in ("http", "https") or not host or is_blocked_host(url):
        return fallback
    return url


def extract_posting(
    provider: Provider, model: str, c: Candidate, page: FetchResult, costs: CostTracker
) -> Posting:
    prompt = (
        f"Job link: {c.url}\nEmployer (from search): {c.employer}\nTitle (from search): {c.title}\n\n"
        f"Page text:\n{page.text[:EXTRACT_INPUT_CHARS]}"
    )
    data, usage = complete_json(
        provider, model=model, system=EXTRACT_SYSTEM, prompt=prompt, schema=EXTRACT_SCHEMA
    )
    costs.add(model, usage)
    pay_min, pay_max = _pay(data.get("pay_min")), _pay(data.get("pay_max"))
    if pay_min is not None and pay_max is not None and pay_min > pay_max:
        pay_min, pay_max = pay_max, pay_min
    posted = None
    raw_date = _clean(data.get("posted_date"))
    if raw_date:
        try:
            posted = date.fromisoformat(raw_date)
        except ValueError:
            posted = None
    mode = _clean(data.get("work_mode"))
    return Posting(
        employer=_clean(data.get("employer")) or c.employer,
        title=_clean(data.get("title")) or c.title,
        requisition_id=_clean(data.get("requisition_id")),
        location=_clean(data.get("location")),
        work_mode=None if mode in (None, "unknown") else mode,
        pay_min=pay_min,
        pay_max=pay_max,
        posted_date=posted,
        apply_url=_apply_url(data.get("apply_url"), c.url),
        description=page.text[:DESCRIPTION_CHARS],
    )
