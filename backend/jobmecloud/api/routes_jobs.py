import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session

from jobmecloud.applydocs.make_docs import NO_SUCH_RESUME_COPY, DocsSetupError, use_as_is
from jobmecloud.applydocs.output import COVER_NAMES, RESUME_NAMES, FileInUseError, document_filename
from jobmecloud.resumes.store import load_index
from jobmecloud.applydocs.service import generate_with_lock
from jobmecloud.config.profile import load_user
from jobmecloud.config.settings import load_settings
from jobmecloud.db.models import Job
from jobmecloud.jobs.runlock import (
    IN_PROGRESS_COPY,
    RunInProgressError,
    acquire_run_lock,
    release_run_lock,
    run_lock_held,
)
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.steps import StepNotConfiguredError

router = APIRouter()

MISSING_JOB_COPY = "No job with that id"
NO_DOCS_COPY = "No documents for this job yet."
FEEDBACK_COPY = "Please keep the feedback under 2,000 characters."
MAX_FEEDBACK = 2000
DOCS_TIMEOUT = timedelta(minutes=6)  # a little over the docs worker's own 5-minute limit
DOCS_TIMED_OUT_COPY = "Writing the documents timed out. Please try again."


class DocsIn(BaseModel):
    feedback: str | None = None
    resume_id: str | None = None  # start from this resume in the library instead of the default


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


def _make(state, job_id: int, feedback: str | None, resume_id: str | None = None) -> dict:
    """Write the documents inside this request (tests and local use)."""
    try:
        result = generate_with_lock(
            state.data_dir, state.engine, state.run_deps, job_id, feedback, datetime.now(timezone.utc), resume_id
        )
        return {"note": result.note, "folder": str(result.folder)}
    except RunInProgressError:
        raise HTTPException(409, IN_PROGRESS_COPY) from None
    except (DocsSetupError, StepNotConfiguredError) as e:
        raise HTTPException(400, str(e)) from None
    except FileInUseError as e:
        raise HTTPException(409, str(e)) from None
    except Exception as e:
        text = friendly_message(e)
        _save_error(state.engine, job_id, text)
        raise HTTPException(502, text) from None


def _start_docs(state, job_id: int, feedback: str | None, resume_id: str | None = None) -> JSONResponse:
    """Hand the writing to a docs worker; the page polls /docs/status until it finishes."""
    if run_lock_held(state.engine, datetime.now(timezone.utc)):
        raise HTTPException(409, IN_PROGRESS_COPY)
    with Session(state.engine) as session:
        job = session.get(Job, job_id)
        job.docs_status, job.docs_error = "generating", None
        job.docs_started_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
    try:
        options = {"feedback": feedback, **({"resume_id": resume_id} if resume_id else {})}
        state.dispatcher.start_docs(job_id, options)
    except Exception:
        text = "Writing the documents could not be started. Please try again."
        _save_error(state.engine, job_id, text)
        _set_docs_status(state.engine, job_id, "error")
        raise HTTPException(502, text) from None
    return JSONResponse({"status": "generating"}, status_code=202)


def _set_docs_status(engine: Engine, job_id: int, status: str) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        job.docs_status = status
        session.add(job)
        session.commit()


@router.post("/jobs/{job_id}/docs")
async def make_job_docs(job_id: int, body: DocsIn, request: Request) -> dict:
    state = request.app.state
    feedback = (body.feedback or "").strip() or None
    if feedback is not None and len(feedback) > MAX_FEEDBACK:
        raise HTTPException(400, FEEDBACK_COPY)
    _require_job(state.engine, job_id)
    resume_id = (body.resume_id or "").strip() or None
    if resume_id not in (None, "auto") and not any(e.id == resume_id for e in load_index(state.data_dir).resumes):
        raise HTTPException(400, NO_SUCH_RESUME_COPY)
    if state.dispatcher.synchronous_docs:
        return await run_in_threadpool(_make, state, job_id, feedback, resume_id)
    return await run_in_threadpool(_start_docs, state, job_id, feedback, resume_id)


@router.get("/jobs/{job_id}/docs/status")
def docs_status(job_id: int, request: Request) -> dict:
    with Session(request.app.state.engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, MISSING_JOB_COPY)
        if job.docs_status == "generating" and _docs_timed_out(job):
            # The worker is gone (timeout, crash): say so instead of leaving the page waiting forever.
            job.docs_status, job.docs_error = "error", DOCS_TIMED_OUT_COPY
            session.add(job)
            session.commit()
        return {"status": job.docs_status, "note": job.docs_note, "folder": job.docs_folder, "error": job.docs_error}


def _docs_timed_out(job: Job) -> bool:
    started = job.docs_started_at
    if started is None:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started > DOCS_TIMEOUT


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
    names = RESUME_NAMES if what == "resume" else COVER_NAMES
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


class DownloadIn(BaseModel):
    what: Literal["resume", "cover_letter"]


@router.post("/jobs/{job_id}/download")
def download_job_file(job_id: int, body: DownloadIn, request: Request) -> dict:
    """A short-lived link to one of the job's documents (AWS only: the files live in S3)."""
    state = request.app.state
    if state.workspace is None:
        raise HTTPException(400, "Downloads are only available in the AWS version.")
    state.workspace.pull()  # the docs worker wrote the files; make sure this Lambda has seen them
    target = _target(state, job_id, body.what)
    try:
        relative = target.resolve().relative_to(Path(state.data_dir).resolve())
    except ValueError:
        raise HTTPException(404, NO_DOCS_COPY) from None
    with Session(state.engine) as session:
        job = session.get(Job, job_id)
        employer, title = (job.employer, job.title) if job else ("", "")
    name = document_filename(load_user(state.data_dir).name, employer, title, body.what, target.suffix)
    return {"url": state.workspace.presign(relative.as_posix(), download_name=name), "filename": name}
