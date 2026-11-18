"""Check a job: read pasted text or a link, and save it as a new job in the tracker."""

import ipaddress
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from sqlmodel import Session, select

from jobmecloud.agents.jobscout.extract import Posting, extract_posting
from jobmecloud.agents.jobscout.liveness import check_page
from jobmecloud.agents.jobscout.rules import code_flags, code_rules
from jobmecloud.agents.jobscout.pipeline import AI_FAILED_FLAG, NOT_READ_FLAG, REPOST_FLAG, UNREADABLE_FLAG
from jobmecloud.agents.jobscout.score import score_job
from jobmecloud.agents.jobscout.search_agent import Candidate
from jobmecloud.config.defaults import STEP_NAMES
from jobmecloud.config.profile import MasterResume, SearchProfile
from jobmecloud.config.settings import Price, ProviderConfig, Settings
from jobmecloud.db.models import Job
from jobmecloud.jobs import tracking
from jobmecloud.jobs.dedup import normalize_url
from jobmecloud.jobs.duplicates import find_duplicate
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult, is_blocked_host
from jobmecloud.llm.steps import StepNotConfiguredError, provider_for_step
from jobmecloud.llm.types import Provider

MIN_PAGE_CHARS = 300
MIN_TEXT_CHARS = 200
CHECK_BUDGET_SECONDS = 24  # the API function stops at 30 seconds; answer plainly before it does
MAX_TEXT_CHARS = 30_000

EMPTY_COPY = "Paste the job's text or its link first."
LINK_COPY = "That doesn't look like a link JobMeCloud can open. Check it, or paste the job's text instead."
LINKEDIN_COPY = "JobMeCloud can't open LinkedIn pages. Open the job, copy its text, and paste the text here instead."
UNREADABLE_COPY = (
    "JobMeCloud couldn't read that page. Open the job, copy its text, and paste the text here instead."
)
CLOSED_COPY = "That posting looks closed, so it was not saved. If you still want it, paste the job's text instead."
TOO_SHORT_COPY = "That is too short to be a job posting. Paste the whole posting, including what the role involves."
TOO_SLOW_COPY = "That took too long. Try again, or pick a faster AI."
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


def within(deadline: float, fn: Callable, *args):
    """Run `fn`, giving up with a plain message once the deadline passes (the work may finish unseen)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CheckError(TOO_SLOW_COPY, 504)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args).result(timeout=remaining)
    except FutureTimeout:
        raise CheckError(TOO_SLOW_COPY, 504)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


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


def _fill_blanks(session: Session, job: Job, posting: Posting, now: datetime) -> None:
    """A job that was added without its details (an import, or by hand) learns them from the posting just read."""
    changed = False
    for field in ("description", "requisition_id", "location", "work_mode", "pay_min", "pay_max", "posted_date"):
        if not getattr(job, field) and getattr(posting, field):
            setattr(job, field, getattr(posting, field))
            changed = True
    if changed:
        session.add(job)
        tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="details_added", at=now,
                     note="Filled in missing details from a pasted posting")
        session.commit()
        session.refresh(job)


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
    deadline = time.monotonic() + CHECK_BUDGET_SECONDS
    kind, text = classify_input(raw)
    if not text:
        raise CheckError(EMPTY_COPY)
    if kind == "text" and len(text) < MIN_TEXT_CHARS:
        raise CheckError(TOO_SHORT_COPY, 422)

    host: str | None = None
    state = "unknown"
    if kind == "link":
        host = _check_link(text)
        known = _known_by_address(session, text)
        if known is not None and (known.description or "").strip():
            return {"status": "duplicate", "job": known, "truncated": False}
        page = within(deadline, fetch, text)
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
    posting = within(deadline, extract_posting, provider, model, candidate, FetchResult(link, 200, body), costs)
    if not posting.employer.strip() or not posting.title.strip():
        raise CheckError(MISSING_COPY, 422)

    url = posting.apply_url or None
    existing = find_duplicate(
        session, employer=posting.employer, title=posting.title, location=posting.location,
        requisition_id=posting.requisition_id, url=url,
    )
    if existing is not None:
        _fill_blanks(session, existing, posting, now)
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


NO_DESCRIPTION_COPY = "This job has no description saved, so there is nothing to judge. Paste the job's text with Check a job instead."
UNKNOWN_MODEL_COPY = "That AI isn't one of your connected choices. Pick one from the list."


def model_choices(settings: Settings) -> list[dict]:
    """The AIs that could judge a job, each once, with the one used for scoring first and preselected."""
    labels = {p.id: p.label for p in settings.providers}
    order = ["score", *[n for n in STEP_NAMES if n != "score"]]
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for step in order:
        sm = settings.steps.get(step)
        if sm is None or sm.provider_id not in labels or (sm.provider_id, sm.model) in seen:
            continue
        seen.add((sm.provider_id, sm.model))
        out.append({"id": step, "label": f"{sm.model} ({labels[sm.provider_id]})", "default": not out})
    return out


@dataclass
class FitResult:
    score: int
    reasons: str
    gaps: str
    warnings: list[str]
    rules: list[dict]
    model: str
    cost: float


def _posting_of(job: Job) -> Posting:
    return Posting(
        employer=job.employer, title=job.title, requisition_id=job.requisition_id, location=job.location,
        work_mode=job.work_mode, pay_min=job.pay_min, pay_max=job.pay_max, posted_date=job.posted_date,
        apply_url=job.apply_url or "", description=job.description,
    )


def fit_job(
    session: Session,
    job: Job,
    *,
    step: str,
    settings: Settings,
    builder: Callable[[ProviderConfig], Provider],
    profile: SearchProfile,
    resume: MasterResume | None,
    today: date,
    now: datetime,
) -> FitResult:
    """Judge how well a saved job fits, with the AI behind `step`; the job changes only if the AI answers."""
    deadline = time.monotonic() + CHECK_BUDGET_SECONDS
    choices = {c["id"] for c in model_choices(settings)}
    if not choices:
        raise StepNotConfiguredError("Connect an AI first.")
    if step not in choices:
        raise CheckError(UNKNOWN_MODEL_COPY)
    if not (job.description or "").strip():
        raise CheckError(NO_DESCRIPTION_COPY, 422)
    provider, model = provider_for_step(settings, step, builder)
    posting = _posting_of(job)
    costs = CostTracker(settings.prices, settings.caps.max_spend_per_run_usd)
    # May raise or run out of time: nothing is touched yet.
    result = within(deadline, score_job, provider, model, posting, profile, resume, costs)

    rules = [r.as_dict() for r in code_rules(posting, profile)] + [d.as_dict() for d in result.deal_breakers]
    kept = [REPOST_FLAG] if REPOST_FLAG in (job.flags or []) else []
    job.match_score, job.reasons, job.gaps = result.score, result.reasons, result.gaps
    job.hard_rules = rules
    job.flags = kept + code_flags(posting, profile, today) + result.warnings
    session.add(job)
    tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="fit_checked", at=now,
                 to_value=str(result.score), note=f"Fit checked with {model}, about ${costs.cost:.2f}")
    session.commit()
    session.refresh(job)
    return FitResult(result.score, result.reasons, result.gaps, result.warnings, rules, model, costs.cost)


@dataclass
class DescriptionResult:
    details_read: bool
    message: str | None
    truncated: bool


_FILLED = ("requisition_id", "location", "work_mode", "pay_min", "pay_max", "posted_date")


def add_description(
    session: Session,
    job: Job,
    *,
    text: str,
    provider: Provider,
    model: str,
    prices: dict[str, Price],
    cap: float,
    now: datetime,
) -> DescriptionResult:
    """Keep a pasted job description on a job that could not be read, and read its details.

    The text is saved first, so it is never lost if reading the details fails or runs out of time. The job's
    employer and title are never changed, and a detail the job already has is never overwritten.
    """
    deadline = time.monotonic() + CHECK_BUDGET_SECONDS
    text = (text or "").strip()
    if len(text) < MIN_TEXT_CHARS:
        raise CheckError(TOO_SHORT_COPY, 422)
    truncated = len(text) > MAX_TEXT_CHARS
    text = text[:MAX_TEXT_CHARS]

    job.description = text[:20_000]
    job.flags = [f for f in (job.flags or []) if f not in (UNREADABLE_FLAG, NOT_READ_FLAG, AI_FAILED_FLAG)]
    session.add(job)
    tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="description_added", at=now,
                 note="Description pasted by hand")
    session.commit()

    try:
        costs = CostTracker(prices, cap)
        candidate = Candidate(url=job.apply_url or "", employer=job.employer, title=job.title)
        posting = within(deadline, extract_posting, provider, model, candidate, FetchResult(candidate.url, 200, text), costs)
    except CheckError as e:
        return DescriptionResult(False, e.message, truncated)
    except Exception as e:  # the text is already kept; a failed read only means the details stay as they were
        from jobmecloud.llm.connection import friendly_message
        return DescriptionResult(False, friendly_message(e), truncated)
    for field in _FILLED:
        if not getattr(job, field) and getattr(posting, field):
            setattr(job, field, getattr(posting, field))
    if job.pay_min or job.pay_max:
        job.pay_verified = True
        job.flags = [f for f in job.flags if f != "Pay unverified"]
    session.add(job)
    session.commit()
    return DescriptionResult(True, None, truncated)
