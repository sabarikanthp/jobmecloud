from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from jobmecloud.config.settings import load_settings, save_settings
from jobmecloud.llm.connection import ConnectionResult, check_provider, check_search
from jobmecloud.llm.factory import build_search
from jobmecloud.llm.search import SearchError
from jobmecloud.secrets import get_secret, set_secret

router = APIRouter()


class ModelIn(BaseModel):
    model: str


class SearchIn(BaseModel):
    backend: Literal["builtin", "tavily", "brave"]
    api_key: str | None = None


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: str, body: ModelIn, request: Request) -> dict:
    settings = load_settings(request.app.state.data_dir)
    cfg = next((p for p in settings.providers if p.id == provider_id), None)
    if cfg is None:
        raise HTTPException(404, "No provider with that id")
    try:
        provider = request.app.state.provider_builder(cfg)
    except Exception as e:
        return asdict(ConnectionResult(False, f"Something went wrong: {e}"))
    return asdict(check_provider(provider, body.model))


@router.get("/search")
def get_search(request: Request) -> dict:
    backend = load_settings(request.app.state.data_dir).search_backend
    has_key = backend != "builtin" and bool(get_secret(f"search:{backend}"))
    return {"backend": backend, "has_key": has_key}


@router.put("/search")
def put_search(body: SearchIn, request: Request) -> dict:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    settings.search_backend = body.backend
    save_settings(data_dir, settings)
    if body.backend != "builtin" and body.api_key and body.api_key.strip():
        set_secret(f"search:{body.backend}", body.api_key)
    has_key = body.backend != "builtin" and bool(get_secret(f"search:{body.backend}"))
    return {"backend": body.backend, "has_key": has_key}


@router.post("/search/test")
def test_search(request: Request) -> dict:
    backend = load_settings(request.app.state.data_dir).search_backend
    if backend == "builtin":
        return asdict(
            ConnectionResult(True, "Built-in search is used with Claude. Nothing to test.")
        )
    try:
        search = build_search(backend)
    except SearchError as e:
        return asdict(ConnectionResult(False, str(e)))
    return asdict(check_search(search))
