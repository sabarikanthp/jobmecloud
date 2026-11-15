"""JobScout step 2: is a posting still open? Code rules first, a model for unclear pages."""

from typing import Literal

from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult, is_blocked_host  # noqa: F401  (re-exported)
from jobmecloud.llm.structured import complete_json
from jobmecloud.llm.types import Provider

CLOSED_PHRASES = (
    "no longer accepting applications",
    "no longer available",
    "position has been filled",
    "job has expired",
    "posting has closed",
    "this job is closed",
    "job not found",
    "no longer open",
)
MIN_READABLE_CHARS = 500
CLASSIFY_CHARS = 8000

LIVENESS_SCHEMA = {
    "type": "object",
    "properties": {"state": {"type": "string", "enum": ["active", "closed", "unknown"]}},
    "required": ["state"],
    "additionalProperties": False,
}

LIVENESS_SYSTEM = (
    "You read job postings and say whether a posting is still open. "
    "Answer active if the page is a live posting that accepts applications, closed if it says "
    "the job is filled, expired or closed, and unknown if you cannot tell."
)


def check_page(page: FetchResult, title: str) -> Literal["active", "closed", "unknown", "unclear"]:
    if page.status in (404, 410):
        return "closed"
    if page.status == 0 or not 200 <= page.status <= 299:
        return "unknown"
    text = page.text.lower()
    if any(phrase in text for phrase in CLOSED_PHRASES):
        return "closed"
    if len(page.text) < MIN_READABLE_CHARS:
        return "unknown"
    if " ".join(title.lower().split()) in " ".join(text.split()):
        return "active"
    return "unclear"


def classify_unclear(
    provider: Provider, model: str, page_text: str, title: str, costs: CostTracker
) -> Literal["active", "closed", "unknown"]:
    prompt = f"Job title: {title}\n\nPage text:\n{page_text[:CLASSIFY_CHARS]}"
    data, usage = complete_json(
        provider, model=model, system=LIVENESS_SYSTEM, prompt=prompt, schema=LIVENESS_SCHEMA
    )
    costs.add(model, usage)
    state = data.get("state")
    return state if state in ("active", "closed") else "unknown"
