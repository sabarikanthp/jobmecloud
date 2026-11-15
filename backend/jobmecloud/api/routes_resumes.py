import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from jobmecloud.api.uploads import read_upload
from jobmecloud.applydocs.pages import original_page_count
from jobmecloud.config.profile import MasterResume
from jobmecloud.config.settings import load_settings
from jobmecloud.importers.text import ImportFileError, extract_text
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.errors import ProviderError
from jobmecloud.llm.steps import StepNotConfiguredError, provider_for_step
from jobmecloud.resumes.mapping import (
    MAP_FAIL_COPY,
    ResumeMapping,
    clean_mapping,
    draft_mapping,
    remap_mapping,
    role_keys,
)
from jobmecloud.resumes.store import (
    ResumeEntry,
    add_resume,
    file_path,
    get_entry,
    kind_for,
    load_index,
    load_mapping,
    load_reading,
    remove_resume,
    save_mapping,
    set_default,
)
from jobmecloud.setup.ai_import import draft_resume

router = APIRouter()

KEEP_UPLOADS = 5
EXPIRED_COPY = "That upload expired. Please upload the file again."
NAME_COPY = "Please give this resume a name."
NO_MAPPING_COPY = "This resume has no mapping."


class ResumeOut(ResumeEntry):
    is_default: bool = False
    pages: int | None = None


class ResumeList(BaseModel):
    default_id: str | None
    resumes: list[ResumeOut]


class SaveIn(BaseModel):
    upload_id: str
    name: str
    reading: MasterResume
    mapping: ResumeMapping | None = None
    make_default: bool = False


def _uploads(request: Request) -> dict[str, dict]:
    state = request.app.state
    if not hasattr(state, "resume_uploads"):
        state.resume_uploads = {}
    return state.resume_uploads


def _entry(request: Request, resume_id: str) -> ResumeEntry:
    try:
        return get_entry(request.app.state.data_dir, resume_id)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


def _pages(data_dir: Path, entry: ResumeEntry) -> int | None:
    if entry.kind != "docx":
        return None
    try:
        return original_page_count(file_path(data_dir, entry).read_bytes())
    except Exception:
        return None


def _out(data_dir: Path, entry: ResumeEntry, default_id: str | None) -> ResumeOut:
    return ResumeOut(**entry.model_dump(), is_default=entry.id == default_id, pages=_pages(data_dir, entry))


@router.post("/resumes/draft")
async def draft(file: UploadFile, request: Request) -> dict:
    filename = file.filename or ""
    try:
        data = await read_upload(file)
        text = await run_in_threadpool(extract_text, filename, data)
        provider, model = provider_for_step(
            load_settings(request.app.state.data_dir), "extract", request.app.state.provider_builder
        )
    except (ImportFileError, StepNotConfiguredError) as e:
        raise HTTPException(400, str(e)) from None
    try:
        reading = await run_in_threadpool(draft_resume, provider, model, text)
    except ProviderError as e:
        raise HTTPException(502, friendly_message(e)) from None
    kind = kind_for(filename)
    mapping, map_error = None, None
    if kind == "docx":
        try:
            drafted = await run_in_threadpool(draft_mapping, provider, model, data, reading)
            if drafted.mapped():
                mapping = drafted
            else:
                map_error = MAP_FAIL_COPY
        except ProviderError as e:
            map_error = friendly_message(e)
    uploads = _uploads(request)
    upload_id = uuid.uuid4().hex
    uploads[upload_id] = {"filename": filename, "data": data, "kind": kind}
    while len(uploads) > KEEP_UPLOADS:
        del uploads[next(iter(uploads))]
    return {
        "upload_id": upload_id,
        "kind": kind,
        "filename": filename,
        "reading": reading.model_dump(mode="json"),
        "mapping": mapping.model_dump(mode="json") if mapping else None,
        "map_error": map_error,
    }


@router.post("/resumes", status_code=201)
def save(body: SaveIn, request: Request) -> ResumeOut:
    upload = _uploads(request).get(body.upload_id)
    if upload is None:
        raise HTTPException(404, EXPIRED_COPY)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, NAME_COPY)
    mapping = None
    if body.mapping is not None and upload["kind"] == "docx":
        # The user may have moved or removed jobs in the reading after the mapping was drafted.
        mapping = clean_mapping(remap_mapping(body.mapping, body.reading), body.reading)
    data_dir = request.app.state.data_dir
    entry = add_resume(
        data_dir,
        name=name,
        filename=upload["filename"],
        data=upload["data"],
        reading=body.reading,
        mapping=mapping,
        make_default=body.make_default,
        now=datetime.now(timezone.utc),
    )
    return _out(data_dir, entry, load_index(data_dir).default_id)


@router.get("/resumes")
def list_resumes(request: Request) -> ResumeList:
    data_dir = request.app.state.data_dir
    index = load_index(data_dir)
    return ResumeList(default_id=index.default_id, resumes=[_out(data_dir, e, index.default_id) for e in index.resumes])


@router.get("/resumes/{resume_id}/reading")
def get_reading(resume_id: str, request: Request) -> MasterResume:
    _entry(request, resume_id)
    return load_reading(request.app.state.data_dir, resume_id)


@router.get("/resumes/{resume_id}/mapping")
def get_mapping(resume_id: str, request: Request) -> ResumeMapping:
    _entry(request, resume_id)
    mapping = load_mapping(request.app.state.data_dir, resume_id)
    if mapping is None:
        raise HTTPException(404, NO_MAPPING_COPY)
    return mapping


@router.put("/resumes/{resume_id}/mapping")
def put_mapping(resume_id: str, body: ResumeMapping, request: Request) -> ResumeMapping:
    if _entry(request, resume_id).kind != "docx":
        raise HTTPException(404, NO_MAPPING_COPY)
    data_dir = request.app.state.data_dir
    reading = load_reading(data_dir, resume_id)
    # The user has just reviewed every label against the stored reading.
    cleaned = clean_mapping(body, reading).model_copy(update={"role_keys": role_keys(reading), "stale": False})
    save_mapping(data_dir, resume_id, cleaned)
    return cleaned


@router.post("/resumes/{resume_id}/default", status_code=204)
def make_default(resume_id: str, request: Request) -> Response:
    _entry(request, resume_id)
    set_default(request.app.state.data_dir, resume_id)
    return Response(status_code=204)


@router.delete("/resumes/{resume_id}", status_code=204)
def delete(resume_id: str, request: Request) -> Response:
    _entry(request, resume_id)
    try:
        remove_resume(request.app.state.data_dir, resume_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return Response(status_code=204)
