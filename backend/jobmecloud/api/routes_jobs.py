import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session

from jobmecloud.applydocs.make_docs import DocsSetupError, make_docs, use_as_is
from jobmecloud.applydocs.output import COVER_NAME, RESUME_NAMES, FileInUseError
from jobmecloud.config.settings import load_settings
from jobmecloud.db.models import Job
from jobmecloud.jobs.runlock import (
    IN_PROGRESS_COPY,
    RunInProgressError,
    acquire_run_lock,
    lock_heartbeat,
    release_run_lock,
)
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.steps import StepNotConfiguredError, provider_for_step

router = APIRouter()

MISSING_JOB_COPY = "No job with that id"
NO_DOCS_COPY = "No documents for this job yet."
FEEDBACK_COPY = "Please keep the feedback under 2,000 characters."
MAX_FEEDBACK = 2000


class DocsIn(BaseModel):
    feedback: str | None = None


class AsIsIn(BaseModel):
    resume_id: str


class OpenIn(BaseModel):
    what: Literal["resume", "cover_letter", "folder"]


def default_open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - the path is built from the job's saved folder only
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def _require_job(engine: Engine, job_id: int) -> None:
    with Session(engine) as session:
        if session.get(Job, job_id) is None:
            raise HTTPException(404, MISSING_JOB_COPY)


def _save_error(engine: Engine, job_id: int, text: str) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is not None:
            job.docs_error = text
            session.add(job)
            session.commit()


def _make(state, job_id: int, feedback: str | None) -> dict:
    now = datetime.now(timezone.utc)
    try:
        owner = acquire_run_lock(state.engine, now)
    except RunInProgressError:
        raise HTTPException(409, IN_PROGRESS_COPY) from None
    try:
        with lock_heartbeat(state.engine, owner):
            return _make_locked(state, job_id, feedback, now)
    finally:
        release_run_lock(state.engine, owner)


def _make_locked(state, job_id: int, feedback: str | None, now: datetime) -> dict:
    try:
        settings = load_settings(state.data_dir)
        provider, model = provider_for_step(settings, "tailor", state.run_deps.provider_builder)
        costs = CostTracker(settings.prices, settings.caps.max_spend_per_run_usd)
        result = make_docs(
            state.data_dir, state.engine, job_id, provider=provider, model=model, costs=costs,
            counter=state.run_deps.page_counter, now=now, feedback=feedback,
        )
        return {"note": result.note, "folder": str(result.folder)}
    except (DocsSetupError, StepNotConfiguredError) as e:
        raise HTTPException(400, str(e)) from None
    except FileInUseError as e:
        raise HTTPException(409, str(e)) from None
    except HTTPException:
        raise
    except Exception as e:
        text = friendly_message(e)
        _save_error(state.engine, job_id, text)
        raise HTTPException(502, text) from None


@router.post("/jobs/{job_id}/docs")
async def make_job_docs(job_id: int, body: DocsIn, request: Request) -> dict:
    state = request.app.state
    feedback = (body.feedback or "").strip() or None
    if feedback is not None and len(feedback) > MAX_FEEDBACK:
        raise HTTPException(400, FEEDBACK_COPY)
    _require_job(state.engine, job_id)
    return await run_in_threadpool(_make, state, job_id, feedback)


def _as_is(state, job_id: int, resume_id: str) -> dict:
    now = datetime.now(timezone.utc)
    # The same lock as runs and Make docs: they write the same job folder.
    try:
        owner = acquire_run_lock(state.engine, now)
    except RunInProgressError:
        raise HTTPException(409, IN_PROGRESS_COPY) from None
    try:
        result = use_as_is(state.data_dir, state.engine, job_id, resume_id, now)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    except DocsSetupError as e:
        raise HTTPException(400, str(e)) from None
    except FileInUseError as e:
        raise HTTPException(409, str(e)) from None
    finally:
        release_run_lock(state.engine, owner)
    return {"note": result.note, "folder": str(result.folder)}


@router.post("/jobs/{job_id}/as-is")
async def job_as_is(job_id: int, body: AsIsIn, request: Request) -> dict:
    state = request.app.state
    _require_job(state.engine, job_id)
    return await run_in_threadpool(_as_is, state, job_id, body.resume_id)


def _target(state, job_id: int, what: str) -> Path:
    with Session(state.engine) as session:
        job = session.get(Job, job_id)
        docs_folder = job.docs_folder if job else None
    if job is None:
        raise HTTPException(404, MISSING_JOB_COPY)
    if not docs_folder:
        raise HTTPException(404, NO_DOCS_COPY)
    folder = Path(docs_folder).resolve()
    apps = load_settings(state.data_dir).applications_path(state.data_dir).resolve()
    if not folder.is_relative_to(apps) or not folder.is_dir():
        raise HTTPException(404, NO_DOCS_COPY)
    if what == "folder":
        return folder
    names = RESUME_NAMES if what == "resume" else (COVER_NAME,)
    for name in names:
        if (folder / name).is_file():
            return folder / name
    raise HTTPException(404, NO_DOCS_COPY)


@router.post("/jobs/{job_id}/open", status_code=204)
def open_job_file(job_id: int, body: OpenIn, request: Request) -> Response:
    state = request.app.state
    target = _target(state, job_id, body.what)
    state.open_path(str(target))
    return Response(status_code=204)
