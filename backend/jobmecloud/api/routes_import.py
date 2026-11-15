import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.db.batch import BATCH_ROWS
from jobmecloud.api.uploads import read_upload
from jobmecloud.db.models import Job, WatchlistEmployer
from jobmecloud.importers.text import ImportFileError
from jobmecloud.importers.tracker import (
    TRACKER_FIELDS,
    Sheet,
    cell_text,
    read_tracker,
    rows_to_jobs,
    suggest_mapping,
)
from jobmecloud.importers.watchlist import (
    WATCHLIST_FIELDS,
    rows_to_employers,
    suggest_watchlist_mapping,
)
from jobmecloud.jobs.dedup import dedup_key, normalize_employer
from jobmecloud.jobs.tracking import log

router = APIRouter()

KEEP_UPLOADS = 5
EXPIRED_COPY = "That upload expired. Please upload the file again."
MAPPING_COPY = "Choose which columns hold the employer and the job title."
NAME_MAPPING_COPY = "Choose which column holds the employer's name."


class CommitIn(BaseModel):
    upload_id: str
    sheet: str
    mapping: dict[str, str | None]


def _uploads(request: Request) -> dict[str, list[Sheet]]:
    state = request.app.state
    if not hasattr(state, "tracker_uploads"):
        state.tracker_uploads = {}
    return state.tracker_uploads


async def _preview(file: UploadFile, request: Request, suggest) -> dict:
    try:
        data = await read_upload(file)
        sheets = await run_in_threadpool(read_tracker, file.filename or "", data)
    except ImportFileError as exc:
        raise HTTPException(400, str(exc)) from exc
    uploads = _uploads(request)
    upload_id = uuid.uuid4().hex
    uploads[upload_id] = sheets
    while len(uploads) > KEEP_UPLOADS:
        del uploads[next(iter(uploads))]
    return {
        "upload_id": upload_id,
        "sheets": [
            {
                "name": s.name,
                "columns": s.columns,
                "sample_rows": [[cell_text(c) for c in r] for r in s.rows[:5]],
                "suggested_mapping": suggest(s.columns),
            }
            for s in sheets
        ],
    }


def _sheet(request: Request, body: CommitIn, fields: tuple[str, ...]) -> tuple[Sheet, dict]:
    sheets = _uploads(request).get(body.upload_id)
    sheet = next((s for s in sheets or [] if s.name == body.sheet), None)
    if sheet is None:
        raise HTTPException(404, EXPIRED_COPY)
    mapping = {f: body.mapping.get(f) or None for f in fields}
    for col in mapping.values():
        if col is not None and col not in sheet.columns:
            raise HTTPException(400, f"That column isn't in the sheet: {col}")
    return sheet, mapping


@router.post("/import/tracker/preview")
async def preview_tracker(file: UploadFile, request: Request) -> dict:
    return await _preview(file, request, suggest_mapping)


def _message(imported: int, duplicates: int, skipped: int, left_out: int = 0) -> str:
    msg = f"Imported {imported} {'job' if imported == 1 else 'jobs'}."
    if duplicates:
        msg += f" {duplicates} {'was' if duplicates == 1 else 'were'} already in JobMe."
    if skipped:
        msg += (
            f" {skipped} {'row' if skipped == 1 else 'rows'} had no employer "
            "or title and was left out."
        )
    if left_out:
        msg += (
            f" {left_out} {'row' if left_out == 1 else 'rows'} over the 5,000-row "
            f"limit {'was' if left_out == 1 else 'were'} left out."
        )
    return msg


@router.post("/import/tracker/commit")
def commit_tracker(body: CommitIn, request: Request) -> dict:
    sheet, mapping = _sheet(request, body, TRACKER_FIELDS)
    if not mapping["employer"] or not mapping["title"]:
        raise HTTPException(400, MAPPING_COPY)

    jobs, skipped = rows_to_jobs(sheet, mapping, datetime.now(timezone.utc).replace(tzinfo=None))
    imported = duplicates = 0
    with Session(request.app.state.engine) as session:
        seen = {
            dedup_key(j.employer, j.requisition_id, j.title, j.location)
            for j in session.exec(select(Job))
        }
        for job in jobs:
            key = dedup_key(job.employer, job.requisition_id, job.title, job.location)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            # The database stores UTC; the importer's naive values are UTC.
            job.first_seen_at = job.first_seen_at.replace(tzinfo=timezone.utc)
            if job.applied_at is not None:
                job.applied_at = job.applied_at.replace(tzinfo=timezone.utc)
            session.add(job)
            session.flush()
            log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="imported",
                at=datetime.now(timezone.utc), actor="user", to_value=job.status)
            imported += 1
            if imported % BATCH_ROWS == 0:
                session.commit()
        session.commit()
    return {
        "imported": imported,
        "duplicates": duplicates,
        "skipped": skipped,
        "message": _message(imported, duplicates, skipped, sheet.left_out),
    }


@router.post("/import/watchlist/preview")
async def preview_watchlist(file: UploadFile, request: Request) -> dict:
    return await _preview(file, request, suggest_watchlist_mapping)


def _watchlist_message(added: int, duplicates: int, skipped: int, left_out: int) -> str:
    msg = f"Added {added} {'employer' if added == 1 else 'employers'}."
    if duplicates:
        msg += f" {duplicates} {'was' if duplicates == 1 else 'were'} already on your list."
    if skipped:
        msg += (
            f" {skipped} {'row' if skipped == 1 else 'rows'} had no employer name "
            f"and {'was' if skipped == 1 else 'were'} left out."
        )
    if left_out:
        msg += (
            f" {left_out} {'row' if left_out == 1 else 'rows'} over the 5,000-row "
            f"limit {'was' if left_out == 1 else 'were'} left out."
        )
    return msg


@router.post("/import/watchlist/commit")
def commit_watchlist(body: CommitIn, request: Request) -> dict:
    sheet, mapping = _sheet(request, body, WATCHLIST_FIELDS)
    if not mapping["name"]:
        raise HTTPException(400, NAME_MAPPING_COPY)
    employers, skipped = rows_to_employers(sheet, mapping)
    added = duplicates = 0
    with Session(request.app.state.engine) as session:
        seen = {normalize_employer(e.name) for e in session.exec(select(WatchlistEmployer))}
        for employer in employers:
            key = normalize_employer(employer.name)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            session.add(employer)
            added += 1
            if added % BATCH_ROWS == 0:
                session.commit()
        session.commit()
    return {
        "imported": added,
        "duplicates": duplicates,
        "skipped": skipped,
        "message": _watchlist_message(added, duplicates, skipped, sheet.left_out),
    }
