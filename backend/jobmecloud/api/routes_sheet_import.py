import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from jobmecloud.api.routes_import import EXPIRED_COPY, KEEP_UPLOADS, _uploads
from jobmecloud.api.uploads import read_upload
from jobmecloud.importers.sheet_helpers import KIND_FIELDS, guess_field_type, guess_kind, suggest_for
from jobmecloud.importers.sheet_import import ImportFailure, SheetImportIn, run_import
from jobmecloud.importers.text import ImportFileError
from jobmecloud.importers.tracker import Sheet, cell_text, read_tracker
from jobmecloud.jobs.tracking import TrackingError

router = APIRouter()


def _kinds() -> dict:
    return {kind: [{"key": f.key, "label": f.label, "help": f.help, "required": f.required}
                   for f in fields] for kind, fields in KIND_FIELDS.items()}


def _columns_info(sheet: Sheet) -> dict:
    info = {}
    for i, col in enumerate(sheet.columns):
        if not col:
            continue
        values = [cell_text(r[i]) for r in sheet.rows if i < len(r)]
        kind, choices = guess_field_type(values)
        info[col] = {"name": col, "type": kind, "choices": choices}
    return info


@router.post("/import/sheet/preview")
async def preview_sheet(file: UploadFile, request: Request) -> dict:
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
        "kinds": _kinds(),
        "sheets": [
            {
                "name": s.name,
                "columns": s.columns,
                "sample_rows": [[cell_text(c) for c in r] for r in s.rows[:5]],
                "guessed_kind": guess_kind(s.name, s.columns),
                "suggested": {kind: suggest_for(kind, s.columns) for kind in KIND_FIELDS},
                "columns_info": _columns_info(s),
            }
            for s in sheets
        ],
    }


@router.post("/import/sheet")
def import_sheet(body: SheetImportIn, request: Request) -> dict:
    sheets = _uploads(request).get(body.upload_id)
    sheet = next((s for s in sheets or [] if s.name == body.sheet), None)
    if sheet is None:
        raise HTTPException(404, EXPIRED_COPY)
    now = datetime.now(timezone.utc)
    with Session(request.app.state.engine) as session:
        try:
            report = run_import(session, sheet, body, now=now)
        except (ImportFailure, TrackingError) as e:
            session.rollback()
            raise HTTPException(400, str(e))
        except Exception:
            session.rollback()
            raise
        if body.dry_run:
            session.rollback()
        else:
            session.commit()
    return report
