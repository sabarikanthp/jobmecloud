import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

import jobmecloud
from jobmecloud.api import (
    routes_check,
    routes_connections,
    routes_contacts,
    routes_dashboard,
    routes_fields,
    routes_followups,
    routes_import,
    routes_inbound,
    routes_joblist,
    routes_jobs,
    routes_models,
    routes_profile,
    routes_resumes,
    routes_runs,
    routes_schedule,
    routes_settings,
    routes_similar,
    routes_setup,
    routes_sheet_import,
    routes_tracking,
    routes_keys,
    routes_watchlist,
)
from jobmecloud.agents.jobscout.pipeline import RunDeps
from jobmecloud.config import paths
from jobmecloud.config.settings import ProviderConfig, Settings, SettingsError, load_settings
from jobmecloud.db.engine import DB_URL_ENV, make_engine
from jobmecloud.db.migrate import migrate
from jobmecloud.db.retry import ConflictRetryMiddleware
from jobmecloud.jobs.dispatch import LambdaDispatcher, ThreadDispatcher
from jobmecloud.llm.factory import build_provider
from jobmecloud.llm.search import CHECK_FETCH_TIMEOUT, fetch_page
from jobmecloud.llm.types import Provider
from jobmecloud.storage.sync import WorkspaceSyncMiddleware
from jobmecloud.storage.workspace import Workspace

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app(
    data_dir: Path | None = None,
    provider_builder: Callable[[ProviderConfig], Provider] = build_provider,
) -> FastAPI:
    data_dir = Path(data_dir) if data_dir is not None else paths.data_dir()
    workspace = None
    if os.environ.get("JOBMECLOUD_BUCKET"):
        # In AWS the data folder is a working copy of an S3 prefix.
        workspace = Workspace(os.environ["JOBMECLOUD_BUCKET"], os.environ.get("JOBMECLOUD_PREFIX", "workspace"), data_dir)
        workspace.pull()
    engine = make_engine(data_dir=data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.engine.dispose()

    app = FastAPI(title="JobMe", version=jobmecloud.__version__, lifespan=lifespan)
    # Innermost first: retry write conflicts, sync the S3 workspace, then check the Host header last of all
    # (outermost), which blocks DNS-rebinding pages.
    app.add_middleware(ConflictRetryMiddleware)
    if workspace is not None:
        app.add_middleware(WorkspaceSyncMiddleware, workspace=workspace)
    hosts = os.environ.get("JOBMECLOUD_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in hosts.split(",") if h.strip()])
    app.state.data_dir = data_dir
    app.state.engine = engine
    app.state.provider_builder = provider_builder
    app.state.run_deps = RunDeps(provider_builder)
    app.state.run_thread = None
    app.state.workspace = workspace
    app.state.dispatcher = (
        LambdaDispatcher() if os.environ.get("JOBMECLOUD_RUN_FUNCTION") else ThreadDispatcher(app.state)
    )
    app.state.open_path = routes_jobs.default_open_path
    app.state.today = date.today
    app.state.check_fetch = lambda url: fetch_page(url, timeout=CHECK_FETCH_TIMEOUT)

    try:
        settings = load_settings(data_dir)
    except SettingsError:
        # A bad settings file is reported by the settings routes, not at startup.
        settings = Settings()
    paths.ensure_dirs(data_dir, settings)
    if not os.environ.get(DB_URL_ENV):
        migrate(engine)  # in AWS the schema is migrated at deploy time

    @app.exception_handler(SettingsError)
    async def _settings_error(_: Request, exc: SettingsError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        # Default handler echoes the request body, which could contain an API key.
        detail = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": detail}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": jobmecloud.__version__}

    app.include_router(routes_settings.router, prefix="/api")
    app.include_router(routes_connections.router, prefix="/api")
    app.include_router(routes_profile.router, prefix="/api")
    app.include_router(routes_setup.router, prefix="/api")
    app.include_router(routes_models.router, prefix="/api")
    app.include_router(routes_watchlist.router, prefix="/api")
    app.include_router(routes_keys.router, prefix="/api")
    app.include_router(routes_import.router, prefix="/api")
    app.include_router(routes_runs.router, prefix="/api")
    app.include_router(routes_inbound.router, prefix="/api")
    app.include_router(routes_schedule.router, prefix="/api")
    app.include_router(routes_resumes.router, prefix="/api")
    app.include_router(routes_check.router, prefix="/api")  # before the {id} routes, so "check" is not read as an id
    app.include_router(routes_similar.router, prefix="/api")
    app.include_router(routes_joblist.router, prefix="/api")
    app.include_router(routes_jobs.router, prefix="/api")
    app.include_router(routes_followups.router, prefix="/api")
    app.include_router(routes_tracking.router, prefix="/api")
    app.include_router(routes_contacts.router, prefix="/api")
    app.include_router(routes_dashboard.router, prefix="/api")
    app.include_router(routes_fields.router, prefix="/api")
    app.include_router(routes_sheet_import.router, prefix="/api")

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
