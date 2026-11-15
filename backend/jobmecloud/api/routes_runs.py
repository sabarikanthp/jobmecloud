import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.agents.jobscout.pipeline import RunSetupError, execute_run, preflight, start_run
from jobmecloud.db.models import Job, Run, RunJob
from jobmecloud.jobs.runlock import IN_PROGRESS_COPY, RunInProgressError, run_lock_held
from jobmecloud.jobs.tracking import allowed_next

router = APIRouter()
log = logging.getLogger(__name__)

MISSING_COPY = "No run with that id"


class RunOut(BaseModel):
    id: int
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    stage: str | None
    running: bool
    found: int
    new: int
    excluded: int
    matched: int
    prepared: int
    errors: list[str]
    est_cost: float


class JobOut(BaseModel):
    id: int
    employer: str
    title: str
    location: str | None
    work_mode: str | None
    pay_min: int | None
    pay_max: int | None
    pay_verified: bool | None
    apply_url: str | None
    source: str | None
    match_score: int | None
    hard_rules: list | dict
    flags: list[str]
    reasons: str | None
    gaps: str | None
    liveness: str | None
    status: str
    repost_of_id: int | None
    docs_folder: str | None
    docs_note: str | None
    docs_error: str | None
    allowed_next: list[str] = []


class RunJobOut(BaseModel):
    outcome: str
    job: JobOut


def _run_out(run: Run, engine) -> RunOut:
    running = run.finished_at is None and run_lock_held(engine, datetime.now(timezone.utc))
    return RunOut(
        id=run.id, trigger=run.trigger, started_at=run.started_at,
        finished_at=run.finished_at, stage=run.stage, running=running,
        found=run.found, new=run.new, excluded=run.excluded, matched=run.matched,
        prepared=run.prepared, errors=[str(e) for e in run.errors or []],
        est_cost=run.est_cost,
    )


def _background(*args) -> None:
    try:
        execute_run(*args)
    except Exception:
        # execute_run already recorded the failure on the Run.
        log.exception("Background run failed")


@router.post("/runs", status_code=202)
def run_now(request: Request) -> dict:
    state = request.app.state
    try:
        preflight(state.data_dir, state.run_deps)
    except RunSetupError as exc:
        raise HTTPException(400, str(exc))
    now = datetime.now(timezone.utc)
    try:
        run_id = start_run(state.engine, "manual", now)
    except RunInProgressError:
        raise HTTPException(409, IN_PROGRESS_COPY)
    thread = threading.Thread(
        target=_background,
        args=(state.data_dir, state.engine, run_id, state.run_deps, now),
        daemon=True,
    )
    state.run_thread = thread
    thread.start()
    return {"run_id": run_id}


@router.get("/runs/latest")
def latest_run(request: Request) -> RunOut | None:
    engine = request.app.state.engine
    with Session(engine) as session:
        run = session.exec(select(Run).order_by(Run.started_at.desc(), Run.id.desc())).first()
        return _run_out(run, engine) if run else None


@router.get("/runs/{run_id}/jobs")
def run_jobs(run_id: int, request: Request) -> list[RunJobOut]:
    with Session(request.app.state.engine) as session:
        if session.get(Run, run_id) is None:
            raise HTTPException(404, MISSING_COPY)
        rows = session.exec(
            select(RunJob, Job).where(RunJob.run_id == run_id, RunJob.job_id == Job.id)
        ).all()
        rows.sort(key=lambda r: (
            r[1].match_score is None, -(r[1].match_score or 0), r[1].employer.lower(),
        ))
        return [
            RunJobOut(outcome=rj.outcome,
                      job=JobOut.model_validate(job, from_attributes=True)
                      .model_copy(update={"allowed_next": allowed_next(job)}))
            for rj, job in rows
        ]
