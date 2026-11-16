"""Check a job: read pasted text or a link, and save it as a new job in the tracker."""

import ipaddress
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from sqlmodel import Session, select

from jobmecloud.agents.jobscout.extract import extract_posting
from jobmecloud.agents.jobscout.liveness import check_page
from jobmecloud.agents.jobscout.rules import code_flags, code_rules
from jobmecloud.agents.jobscout.search_agent import Candidate
from jobmecloud.config.profile import SearchProfile
from jobmecloud.config.settings import Price
from jobmecloud.db.models import Job
from jobmecloud.jobs import tracking
from jobmecloud.jobs.dedup import normalize_url
from jobmecloud.jobs.duplicates import find_duplicate
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult, is_blocked_host
from jobmecloud.llm.types import Provider

MIN_PAGE_CHARS = 300
MAX_TEXT_CHARS = 30_000

EMPTY_COPY = "Paste the job's text or its link first."
LINK_COPY = "That doesn't look like a link JobMeCloud can open. Check it, or paste the job's text instead."
LINKEDIN_COPY = "JobMeCloud can't open LinkedIn pages. Open the job, copy its text, and paste the text here instead."
UNREADABLE_COPY = (
    "JobMeCloud couldn't read that page. Open the job, copy its text, and paste the text here instead."
)
CLOSED_COPY = "That posting looks closed, so it was not saved. If you still want it, paste the job's text instead."
MISSING_COPY = (
    "Couldn't tell the employer and job title from that. Include them in the text and try again, "
    "or add the job by hand."
)


class CheckError(Exception):
    """Something the person can fix; `message` is shown as is."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class ReadResult(TypedDict):
    status: Literal["created", "duplicate"]
    job: Job
    truncated: bool


def classify_input(raw: str) -> tuple[Literal["link", "text"], str]:
    """A single address is a link (non-web ones are refused later); anything else is the job's text."""
    text = (raw or "").strip()
    if "://" in text and not any(c.isspace() for c in text):
        return "link", text
    return "text", text


def _check_link(url: str) -> str:
    """The link's host, or a CheckError. Real network safety is enforced again when the page is fetched."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        raise CheckError(LINK_COPY)
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise CheckError(LINK_COPY)
    if is_blocked_host(url):
        raise CheckError(LINKEDIN_COPY)
    try:
        private = not ipaddress.ip_address(host).is_global
    except ValueError:
        private = "." not in host or host.endswith((".local", ".internal", ".localhost"))
    if private:
        raise CheckError(LINK_COPY)
    return host


def _known_by_address(session: Session, url: str) -> Job | None:
    wanted = normalize_url(url)
    for job in session.exec(select(Job)):
        if job.apply_url and normalize_url(job.apply_url) == wanted:
            return job
    return None


def read_job(
    session: Session,
    *,
    raw: str,
    provider: Provider,
    model: str,
    fetch: Callable[[str], FetchResult],
    profile: SearchProfile,
    today: date,
    now: datetime,
    prices: dict[str, Price],
    cap: float,
) -> ReadResult:
    kind, text = classify_input(raw)
    if not text:
        raise CheckError(EMPTY_COPY)

    host: str | None = None
    state = "unknown"
    if kind == "link":
        host = _check_link(text)
        known = _known_by_address(session, text)
        if known is not None:
            return {"status": "duplicate", "job": known, "truncated": False}
        page = fetch(text)
        state = check_page(page, "")
        if state == "closed":
            raise CheckError(CLOSED_COPY, 422)
        if not 200 <= page.status <= 299 or len(page.text.strip()) < MIN_PAGE_CHARS:
            raise CheckError(UNREADABLE_COPY, 422)
        body, link = page.text, text
    else:
        body, link = text, ""

    truncated = len(body) > MAX_TEXT_CHARS
    body = body[:MAX_TEXT_CHARS]
    costs = CostTracker(prices, cap)
    candidate = Candidate(url=link, employer="", title="")
    posting = extract_posting(provider, model, candidate, FetchResult(link, 200, body), costs)
    if not posting.employer.strip() or not posting.title.strip():
        raise CheckError(MISSING_COPY, 422)

    url = posting.apply_url or None
    existing = find_duplicate(
        session, employer=posting.employer, title=posting.title, location=posting.location,
        requisition_id=posting.requisition_id, url=url,
    )
    if existing is not None:
        return {"status": "duplicate", "job": existing, "truncated": truncated}

    job = Job(
        employer=posting.employer, title=posting.title, requisition_id=posting.requisition_id,
        location=posting.location, work_mode=posting.work_mode, pay_min=posting.pay_min,
        pay_max=posting.pay_max, pay_verified=posting.pay_min is not None or posting.pay_max is not None,
        posted_date=posting.posted_date, apply_url=url, source=host or "Pasted text",
        description=posting.description, origin="manual", status="New", first_seen_at=now,
        last_checked_at=now, liveness="active" if state == "active" else "unknown",
        flags=code_flags(posting, profile, today),
        hard_rules=[r.as_dict() for r in code_rules(posting, profile)],
    )
    session.add(job)
    session.flush()
    note = f"Checked with AI, read with {model}" + (f" (about ${costs.cost:.2f})" if costs.cost >= 0.005 else "")
    tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="added", at=now, note=note)
    session.commit()
    session.refresh(job)
    return {"status": "created", "job": job, "truncated": truncated}
