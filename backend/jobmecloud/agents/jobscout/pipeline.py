"""JobScout run pipeline: search, then read, de-duplicate, check and score each job,
then make documents for the top matches.

A run holds the run lock and shares one cost cap across every AI step. Progress
(stage, counts, errors) is committed as the run goes, so a concurrent reader can
follow it. Each step uses a short-lived database session.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from jobmecloud.agents.jobscout.extract import Posting, extract_posting, posting_from_candidate
from jobmecloud.agents.jobscout.liveness import check_page, classify_unclear, is_blocked_host
from jobmecloud.agents.jobscout.rules import code_flags, code_rules
from jobmecloud.agents.jobscout.score import score_job
from jobmecloud.agents.jobscout.search_agent import Candidate, find_candidates, todays_watchlist
from jobmecloud.applydocs.make_docs import STAGE_WRITING, DocsSetupError, make_docs
from jobmecloud.applydocs.output import FileInUseError
from jobmecloud.applydocs.pages import PageCounter, unverified_page_counter
from jobmecloud.config.profile import MasterResume, SearchProfile, load_resume, load_search
from jobmecloud.config.settings import DAYS, ProviderConfig, Settings, load_settings
from jobmecloud.db.models import Job, Run, RunJob, WatchlistEmployer
from jobmecloud.db.retry import retry_on_conflict
from jobmecloud.jobs.dedup import dedup_key, fallback_key, normalize_url
from jobmecloud.jobs.tracking import change_status, log
from contextlib import nullcontext

from jobmecloud.jobs.runlock import HEARTBEAT_SECONDS, acquire_run_lock, lock_heartbeat, release_run_lock
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.errors import ProviderError
from jobmecloud.llm.factory import build_search
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult, SearchBackend, SearchError, fetch_page
from jobmecloud.llm.steps import StepNotConfiguredError, provider_for_step
from jobmecloud.llm.types import Provider
from jobmecloud.resumes.store import default_entry

COST_CAP_COPY = "Stopped early: this run reached its spending limit (${cap:.2f})."
UNREADABLE_FLAG = "Couldn't read the posting"
NOT_READ_FLAG = "Not read: spending limit reached"
AI_FAILED_FLAG = "Not read: the AI step failed"
REPOST_FLAG = "Repost"
NO_ROLES_COPY = "Add at least one job title in What you're looking for."
NO_SEARCH_SERVICE_COPY = "Choose a search service (Tavily or Brave) in Settings > AI connection."
NO_SEARCH_KEY_COPY = "Add your search key in Settings > AI connection."
STAGE_SEARCHING = "Searching for jobs"
STAGE_READING = "Reading postings ({i} of {n})"
STAGE_RECHECK = "Checking older jobs"

STEPS = ("search", "extract", "liveness", "score", "tailor")


class RunLostError(Exception):
    """This run's lock was taken over (the computer was probably asleep), so it must stop."""


STOPPED_EARLY_COPY = "Stopped early to stay within the time limit."
LOST_COPY = "This run stopped because another run took over (the computer may have been asleep)."


def _still_mine(beat) -> None:
    if beat is not None and beat.lost.is_set():
        raise RunLostError(LOST_COPY)


class RunSetupError(Exception):
    """A run can't start; the message is shown to the user."""


@dataclass
class RunDeps:
    provider_builder: Callable[[ProviderConfig], Provider]
    search_builder: Callable[[str], SearchBackend] = build_search
    fetch: Callable[[str], FetchResult] = fetch_page
    page_counter: PageCounter = unverified_page_counter
    should_stop: Callable[[], bool] = lambda: False  # true when the Lambda is nearly out of time


@dataclass
class _Context:
    """Everything one run needs, resolved once at the start."""

    data_dir: Path
    engine: Engine
    run_id: int
    deps: RunDeps
    now: datetime
    settings: Settings
    profile: SearchProfile
    resume: MasterResume | None
    models: dict[str, tuple[Provider, str]]
    costs: CostTracker
    found: int = 0
    new: int = 0
    excluded: int = 0
    matched: int = 0
    prepared: int = 0
    errors: list[str] = field(default_factory=list)
    cost_cap_noted: bool = False
    ai_errors_seen: set[str] = field(default_factory=set)
    stopped: bool = False


@dataclass
class _Indexes:
    """Known jobs by normalized URL, dedup key and fallback key, as job ids."""

    url: dict[str, int] = field(default_factory=dict)
    key: dict[str, int] = field(default_factory=dict)
    fallback: dict[str, int] = field(default_factory=dict)

    def add(self, job: Job, *urls: str) -> None:
        for u in (job.apply_url, *urls):
            if u:
                self.url.setdefault(normalize_url(u), job.id)
        self.key.setdefault(dedup_key(job.employer, job.requisition_id, job.title, job.location), job.id)
        self.fallback.setdefault(fallback_key(job.employer, job.title, job.location), job.id)


# ---------------------------------------------------------------- entry points


def preflight(data_dir: Path, deps: RunDeps) -> None:
    settings = load_settings(data_dir)
    models = _resolve_models(settings, deps)
    if not load_search(data_dir).target_roles:
        raise RunSetupError(NO_ROLES_COPY)
    _resolve_search(settings, models["search"][0], deps)


def start_run(engine: Engine, trigger: Literal["manual", "schedule"], now: datetime) -> int:
    owner = acquire_run_lock(engine, now)
    try:
        with Session(engine) as session:
            run = Run(trigger=trigger, started_at=now, stage=STAGE_SEARCHING, lock_owner=owner)
            session.add(run)
            session.commit()
            return run.id
    except BaseException:
        release_run_lock(engine, owner)
        raise


def abandon_run(engine: Engine, run_id: int, message: str, now: datetime) -> None:
    """Close a run that was started but never handed to a worker, and give its lock back."""
    with Session(engine) as session:
        run = session.get(Run, run_id)
        owner = run.lock_owner
        run.finished_at, run.stage, run.errors = now, None, [message]
        session.add(run)
        session.commit()
    release_run_lock(engine, owner)


def record_failed_run(engine: Engine, trigger: Literal["manual", "schedule"], now: datetime, message: str) -> int:
    """A run that could not even start still leaves a finished Run, so Today can show what went wrong."""
    with Session(engine) as session:
        run = Run(trigger=trigger, started_at=now, finished_at=now, errors=[message])
        session.add(run)
        session.commit()
        return run.id


def execute_run(data_dir: Path, engine: Engine, run_id: int, deps: RunDeps, now: datetime) -> Run:
    ctx: _Context | None = None
    fatal: str | None = None
    with Session(engine) as session:
        owner = session.get(Run, run_id).lock_owner
    try:
        # The heartbeat keeps the lock fresh through long steps; a run that dies stops beating.
        with lock_heartbeat(engine, owner, HEARTBEAT_SECONDS) if owner else nullcontext() as beat:
            settings = load_settings(data_dir)
            ctx = _Context(
                data_dir=data_dir,
                engine=engine,
                run_id=run_id,
                deps=deps,
                now=now,
                settings=settings,
                profile=load_search(data_dir),
                resume=load_resume(data_dir),
                models=_resolve_models(settings, deps),
                costs=CostTracker(settings.prices, settings.caps.max_spend_per_run_usd),
            )
            candidates = _search(ctx)
            _still_mine(beat)
            indexes = _load_indexes(ctx)
            _read_candidates(ctx, candidates, indexes)
            _still_mine(beat)
            _prepare_docs(ctx)
            _still_mine(beat)
            _recheck_older_jobs(ctx)
    except Exception as e:
        fatal = str(e) if isinstance(e, (RunSetupError, RunLostError)) else friendly_message(e)
        raise
    finally:
        try:
            _finish(engine, run_id, ctx, fatal)
        finally:
            release_run_lock(engine, owner)
    with Session(engine) as session:
        return session.get(Run, run_id)


def run_jobscout(
    data_dir: Path,
    engine: Engine,
    deps: RunDeps,
    trigger: Literal["manual", "schedule"],
    now: datetime | None = None,
) -> Run:
    now = now or datetime.now(timezone.utc)
    preflight(data_dir, deps)
    run_id = start_run(engine, trigger, now)
    return execute_run(data_dir, engine, run_id, deps, now)


# ---------------------------------------------------------------- setup helpers


def _resolve_models(settings: Settings, deps: RunDeps) -> dict[str, tuple[Provider, str]]:
    try:
        return {step: provider_for_step(settings, step, deps.provider_builder) for step in STEPS}
    except StepNotConfiguredError as e:
        raise RunSetupError(str(e)) from e


def _resolve_search(settings: Settings, provider: Provider, deps: RunDeps) -> SearchBackend | None:
    """None means the provider's built-in search; raises RunSetupError with user copy."""
    if settings.search_backend == "builtin":
        if getattr(provider, "supports_builtin_search", False):
            return None
        raise RunSetupError(NO_SEARCH_SERVICE_COPY)
    try:
        return deps.search_builder(settings.search_backend)
    except SearchError as e:
        raise RunSetupError(NO_SEARCH_KEY_COPY) from e


# ---------------------------------------------------------------- 1. search


def _search(ctx: _Context) -> list[Candidate]:
    if ctx.settings.caps.max_searches_per_run == 0:
        # No searches allowed: skip the step (and its AI call) entirely.
        _save_progress(ctx)
        return []
    day = DAYS[ctx.now.astimezone().weekday()]
    with Session(ctx.engine) as session:
        watchlist = todays_watchlist(list(session.exec(select(WatchlistEmployer)).all()), day)
    candidates: list[Candidate] = []
    provider, model = ctx.models["search"]
    try:
        search = _resolve_search(ctx.settings, provider, ctx.deps)
        result = find_candidates(
            provider,
            model,
            profile=ctx.profile,
            day=day,
            watchlist=watchlist,
            engine=ctx.engine,
            costs=ctx.costs,
            search=search,
            max_searches=ctx.settings.caps.max_searches_per_run,
            candidates=candidates,
            fetch=ctx.deps.fetch,
        )
    except RunSetupError as e:
        ctx.errors.append(f"Search: {e}")
    except Exception as e:
        ctx.errors.append(f"Search: {friendly_message(e)}")
    else:
        logs = Path(ctx.data_dir) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / f"run-{ctx.run_id}-search.json").write_text(
            json.dumps(result.transcript, indent=2), encoding="utf-8"
        )
    ids = [e.id for e in watchlist]
    with Session(ctx.engine) as session:
        for employer in session.exec(select(WatchlistEmployer).where(WatchlistEmployer.id.in_(ids))):
            employer.last_checked_at = ctx.now
            session.add(employer)
        session.commit()
    ctx.found = len(candidates)
    _save_progress(ctx)
    return candidates


# ---------------------------------------------------------------- 2. indexes


def _load_indexes(ctx: _Context) -> _Indexes:
    indexes = _Indexes()
    with Session(ctx.engine) as session:
        for job in session.exec(select(Job)):
            indexes.add(job)
    return indexes


# ---------------------------------------------------------------- 3. each candidate


def _read_candidates(ctx: _Context, candidates: list[Candidate], indexes: _Indexes) -> None:
    n = len(candidates)
    for i, c in enumerate(candidates, 1):
        if _out_of_time(ctx):
            break
        _save_progress(ctx, stage=STAGE_READING.format(i=i, n=n))
        try:
            _read_one(ctx, c, indexes)
        except Exception as e:
            ctx.errors.append(f"{c.employer} - {c.title}: {friendly_message(e)}")


def _read_one(ctx: _Context, c: Candidate, indexes: _Indexes) -> None:
    known = indexes.url.get(normalize_url(c.url))
    if known is not None:
        _mark_duplicate(ctx, known)
        return

    if ctx.costs.exceeded:
        _save_unread(ctx, c, indexes)
        return

    try:
        _read_new(ctx, c, indexes)
    except ProviderError as e:
        # An AI step failed: keep the job (unread) instead of losing it.
        _save_ai_failed(ctx, c, indexes, e)


def _read_new(ctx: _Context, c: Candidate, indexes: _Indexes) -> None:
    page = FetchResult(c.url, 0, "") if is_blocked_host(c.url) else ctx.deps.fetch(c.url)
    state = check_page(page, c.title)
    readable = state in ("active", "unclear")
    if readable:
        provider, model = ctx.models["extract"]
        posting = extract_posting(provider, model, c, page, ctx.costs)
    else:
        posting = posting_from_candidate(c)

    key = dedup_key(posting.employer, posting.requisition_id, posting.title, posting.location)
    if key in indexes.key:
        _mark_duplicate(ctx, indexes.key[key])
        return
    repost_of = indexes.fallback.get(fallback_key(posting.employer, posting.title, posting.location))

    if state == "unclear":
        provider, model = ctx.models["liveness"]
        state = classify_unclear(provider, model, page.text, c.title, ctx.costs)

    job = _job_from_posting(ctx, posting, c, state)
    job.repost_of_id = repost_of
    flags = [REPOST_FLAG] if repost_of is not None else []
    if readable:
        flags += code_flags(posting, ctx.profile, ctx.now.astimezone().date())
    else:
        flags.append(UNREADABLE_FLAG)
    rules = code_rules(posting, ctx.profile)
    hard_rules = [r.as_dict() for r in rules]

    if state == "closed":
        outcome = "closed"
    elif any(not r.passed for r in rules):
        outcome = "excluded"
    elif readable:
        provider, model = ctx.models["score"]
        result = score_job(provider, model, posting, ctx.profile, ctx.resume, ctx.costs)
        job.match_score, job.reasons, job.gaps = result.score, result.reasons, result.gaps
        hard_rules += [d.as_dict() for d in result.deal_breakers]
        flags += result.warnings
        if any(not d.passed for d in result.deal_breakers):
            outcome = "excluded"
        elif result.score >= ctx.settings.match_cutoff:
            outcome = "matched"
        else:
            outcome = "new"
    else:
        outcome = "new"

    job.flags, job.hard_rules = flags, hard_rules
    _save_new_job(ctx, job, outcome, indexes, c.url)


def _job_from_posting(ctx: _Context, posting: Posting, c: Candidate, state: str) -> Job:
    return Job(
        employer=posting.employer,
        title=posting.title,
        requisition_id=posting.requisition_id,
        location=posting.location,
        work_mode=posting.work_mode,
        pay_min=posting.pay_min,
        pay_max=posting.pay_max,
        pay_verified=posting.pay_max is not None or posting.pay_min is not None,
        posted_date=posting.posted_date,
        apply_url=posting.apply_url,
        source=_host(c.url),
        description=posting.description,
        origin="scout",
        first_seen_at=ctx.now,
        last_checked_at=ctx.now,
        liveness=state,
        status="Closed" if state == "closed" else "New",
    )


def _save_unread(ctx: _Context, c: Candidate, indexes: _Indexes) -> None:
    job = _job_from_posting(ctx, posting_from_candidate(c), c, "unknown")
    job.flags = [NOT_READ_FLAG]
    _note_cost_cap(ctx)
    _save_new_job(ctx, job, "new", indexes, c.url)


def _save_ai_failed(ctx: _Context, c: Candidate, indexes: _Indexes, error: Exception) -> None:
    """Save the job as found; report each distinct AI error once, not once per job."""
    message = friendly_message(error)
    if message not in ctx.ai_errors_seen:
        ctx.ai_errors_seen.add(message)
        ctx.errors.append(f"{c.employer} - {c.title}: {message}")
    job = _job_from_posting(ctx, posting_from_candidate(c), c, "unknown")
    job.flags = [AI_FAILED_FLAG]
    _save_new_job(ctx, job, "new", indexes, c.url)


@retry_on_conflict()
def _mark_duplicate(ctx: _Context, job_id: int) -> None:
    with Session(ctx.engine) as session:
        job = session.get(Job, job_id)
        job.last_checked_at = ctx.now
        session.add(job)
        session.add(RunJob(run_id=ctx.run_id, job_id=job_id, outcome="duplicate"))
        session.commit()


@retry_on_conflict()
def _insert_job(ctx: _Context, job: Job, outcome: str) -> None:
    with Session(ctx.engine) as session:
        session.add(job)
        session.flush()
        log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="found",
            at=ctx.now, actor="system", to_value=job.status, note=job.source)
        session.add(RunJob(run_id=ctx.run_id, job_id=job.id, outcome=outcome))
        session.commit()
        session.refresh(job)


def _save_new_job(ctx: _Context, job: Job, outcome: str, indexes: _Indexes, url: str) -> None:
    _insert_job(ctx, job, outcome)
    indexes.add(job, url)
    ctx.new += 1
    if outcome == "excluded":
        ctx.excluded += 1
    elif outcome == "matched":
        ctx.matched += 1


def _out_of_time(ctx: _Context) -> bool:
    """True once the worker is nearly out of time; the first call records why the run ended early."""
    if not ctx.deps.should_stop():
        return False
    if not ctx.stopped:
        ctx.stopped = True
        ctx.errors.append(STOPPED_EARLY_COPY)
    return True


def _note_cost_cap(ctx: _Context) -> None:
    if not ctx.cost_cap_noted:
        ctx.errors.append(COST_CAP_COPY.format(cap=ctx.settings.caps.max_spend_per_run_usd))
        ctx.cost_cap_noted = True


def _host(url: str) -> str | None:
    try:
        return urlsplit(url.strip()).hostname
    except ValueError:
        return None


# ---------------------------------------------------------------- 4. documents for the top matches


def _prepare_docs(ctx: _Context) -> None:
    if default_entry(ctx.data_dir) is None:
        # No resume uploaded yet: documents are an optional step, so skip without an error.
        return
    with Session(ctx.engine) as session:
        rows = session.exec(
            select(RunJob.id, Job.id, Job.employer, Job.title)
            .join(Job, Job.id == RunJob.job_id)
            .where(RunJob.run_id == ctx.run_id, RunJob.outcome == "matched")
            .order_by(Job.match_score.desc(), Job.id)
            .limit(ctx.settings.caps.max_applications_per_run)
        ).all()
    provider, model = ctx.models["tailor"]
    for i, (run_job_id, job_id, employer, title) in enumerate(rows, 1):
        if _out_of_time(ctx):
            return
        _save_progress(ctx, stage=STAGE_WRITING.format(i=i, n=len(rows)))
        if ctx.costs.exceeded:
            _note_cost_cap(ctx)
            return
        try:
            make_docs(ctx.data_dir, ctx.engine, job_id, provider=provider, model=model, costs=ctx.costs,
                      counter=ctx.deps.page_counter, now=ctx.now)
        except DocsSetupError as e:
            ctx.errors.append(str(e))
            return
        except Exception as e:
            message = str(e) if isinstance(e, FileInUseError) else friendly_message(e)
            _save_docs_error(ctx, job_id, message)
            ctx.errors.append(f"{employer} - {title}: {message}")
        else:
            _mark_prepared(ctx, run_job_id)


def _save_docs_error(ctx: _Context, job_id: int, message: str) -> None:
    with Session(ctx.engine) as session:
        job = session.get(Job, job_id)
        job.docs_error = message
        session.add(job)
        session.commit()


def _mark_prepared(ctx: _Context, run_job_id: int) -> None:
    with Session(ctx.engine) as session:
        run_job = session.get(RunJob, run_job_id)
        run_job.outcome = "prepared"
        session.add(run_job)
        session.commit()
    ctx.prepared += 1


# ---------------------------------------------------------------- 5. recheck


RECHECK_DAYS = 30


def _worth_rechecking(job: Job, since: datetime) -> bool:
    """Recent jobs that passed the rules and were actually read; the rest never change."""
    seen = job.first_seen_at if job.first_seen_at.tzinfo else job.first_seen_at.replace(tzinfo=timezone.utc)
    failed = any(not r.get("passed", True) for r in (job.hard_rules or []) if isinstance(r, dict))
    return seen >= since and not failed and NOT_READ_FLAG not in (job.flags or [])


def _recheck_older_jobs(ctx: _Context) -> None:
    _save_progress(ctx, stage=STAGE_RECHECK)
    since = ctx.now - timedelta(days=RECHECK_DAYS)
    with Session(ctx.engine) as session:
        in_run = set(session.exec(select(RunJob.job_id).where(RunJob.run_id == ctx.run_id)))
        due = [
            (j.id, j.employer, j.title, j.apply_url)
            for j in session.exec(
                select(Job).where(Job.origin == "scout", Job.status.in_(("New", "Ready")))
            )
            if j.apply_url and not is_blocked_host(j.apply_url) and j.id not in in_run
            and _worth_rechecking(j, since)
        ]
    for job_id, employer, title, url in due:
        if _out_of_time(ctx):
            break
        try:
            _recheck_one(ctx, job_id, title, url)
        except Exception as e:
            ctx.errors.append(f"{employer} - {title}: {friendly_message(e)}")


def _recheck_one(ctx: _Context, job_id: int, title: str, url: str) -> None:
    page = ctx.deps.fetch(url)
    state = check_page(page, title)
    if state == "unclear":
        if ctx.costs.exceeded:
            state = "unknown"
        else:
            provider, model = ctx.models["liveness"]
            state = classify_unclear(provider, model, page.text, title, ctx.costs)
    with Session(ctx.engine) as session:
        job = session.get(Job, job_id)
        if state != "unknown" or not job.liveness:  # a failed check never erases a known answer
            job.liveness = state
        job.last_checked_at = ctx.now
        if state == "closed" and job.status in ("New", "Ready"):
            change_status(session, job, "Closed", actor="system", at=ctx.now)
            session.add(RunJob(run_id=ctx.run_id, job_id=job_id, outcome="closed"))
        session.add(job)
        session.commit()


# ---------------------------------------------------------------- 6. totals


def _save_progress(ctx: _Context, **extra) -> None:
    """Commit counts, errors and any extra Run fields so readers can follow the run."""
    _update_run(
        ctx.engine,
        ctx.run_id,
        found=ctx.found,
        new=ctx.new,
        excluded=ctx.excluded,
        matched=ctx.matched,
        prepared=ctx.prepared,
        errors=list(ctx.errors),
        **extra,
    )


def _finish(engine: Engine, run_id: int, ctx: _Context | None, fatal: str | None) -> None:
    done = {"finished_at": datetime.now(timezone.utc), "stage": None}
    if ctx is None:
        _update_run(engine, run_id, errors=[fatal] if fatal else [], **done)
        return
    if fatal:
        ctx.errors.append(fatal)
    _save_progress(
        ctx,
        input_tokens=ctx.costs.input_tokens,
        output_tokens=ctx.costs.output_tokens,
        est_cost=round(ctx.costs.cost, 4),
        **done,
    )


@retry_on_conflict()
def _update_run(engine: Engine, run_id: int, **fields) -> None:
    with Session(engine) as session:
        run = session.get(Run, run_id)
        for name, value in fields.items():
            setattr(run, name, value)
        session.add(run)
        session.commit()
