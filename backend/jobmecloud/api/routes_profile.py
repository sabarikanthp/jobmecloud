from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from jobmecloud.api.uploads import read_upload
from jobmecloud.config.profile import (
    MasterResume,
    SearchProfile,
    UserProfile,
    load_resume,
    load_search,
    load_user,
    save_resume,
    save_search,
    save_user,
)
from jobmecloud.config.settings import load_settings
from jobmecloud.importers.text import ImportFileError, extract_text
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.errors import ProviderError
from jobmecloud.llm.steps import StepNotConfiguredError, provider_for_step
from jobmecloud.resumes.mapping import remap_mapping
from jobmecloud.resumes.store import default_entry, load_mapping, save_mapping, save_reading
from jobmecloud.setup.ai_import import draft_search_profile

router = APIRouter()


@router.get("/profile/user")
def get_user(request: Request) -> UserProfile:
    return load_user(request.app.state.data_dir)


@router.put("/profile/user")
def put_user(body: UserProfile, request: Request) -> UserProfile:
    save_user(request.app.state.data_dir, body)
    return body


@router.get("/profile/search")
def get_search(request: Request) -> SearchProfile:
    return load_search(request.app.state.data_dir)


@router.put("/profile/search")
def put_search(body: SearchProfile, request: Request) -> SearchProfile:
    save_search(request.app.state.data_dir, body)
    return body


@router.get("/profile/resume")
def get_resume(request: Request) -> MasterResume | None:
    return load_resume(request.app.state.data_dir)


@router.put("/profile/resume")
def put_resume(body: MasterResume, request: Request) -> MasterResume:
    data_dir = request.app.state.data_dir
    save_resume(data_dir, body)
    default = default_entry(data_dir)
    if default is not None:
        save_reading(data_dir, default.id, body)
        mapping = load_mapping(data_dir, default.id) if default.kind == "docx" else None
        if mapping is not None:
            # Bullet labels point at jobs by position: follow moved jobs, or mark the mapping stale.
            save_mapping(data_dir, default.id, remap_mapping(mapping, body))
    return body


async def _run_import(file: UploadFile, request: Request, draft):
    try:
        data = await read_upload(file)
        text = await run_in_threadpool(extract_text, file.filename or "", data)
        provider, model = provider_for_step(
            load_settings(request.app.state.data_dir), "extract", request.app.state.provider_builder
        )
    except (ImportFileError, StepNotConfiguredError) as e:
        raise HTTPException(400, str(e)) from None
    try:
        return await run_in_threadpool(draft, provider, model, text)
    except ProviderError as e:
        raise HTTPException(502, friendly_message(e)) from None


@router.post("/profile/search/import")
async def import_search(file: UploadFile, request: Request) -> SearchProfile:
    return await _run_import(file, request, draft_search_profile)
