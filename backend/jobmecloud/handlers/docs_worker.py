"""Lambda entry point for "Make docs": writes one job's resume and cover letter."""

import logging
from datetime import datetime, timezone

from sqlmodel import Session

from jobmecloud.agents.jobscout.pipeline import RunDeps
from jobmecloud.applydocs.make_docs import DocsSetupError
from jobmecloud.applydocs.output import FileInUseError
from jobmecloud.applydocs.service import generate_with_lock
from jobmecloud.config.settings import SettingsError, load_settings
from jobmecloud.db.models import Job
from jobmecloud.handlers.common import bootstrap
from jobmecloud.jobs.runlock import IN_PROGRESS_COPY, RunInProgressError
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.factory import build_provider
from jobmecloud.llm.redact import redact
from jobmecloud.llm.steps import StepNotConfiguredError
from jobmecloud.secrets import get_secret

log = logging.getLogger(__name__)


def build_deps(context) -> RunDeps:
    return RunDeps(provider_builder=build_provider)


def _known_keys(data_dir) -> list[str]:
    try:
        provider_ids = [p.id for p in load_settings(data_dir).providers]
    except SettingsError:
        provider_ids = []
    names = [f"provider:{i}" for i in provider_ids] + ["search:tavily", "search:brave"]
    return [v for v in (get_secret(n) for n in names) if v]


def _finish(engine, job_id: int, status: str, error: str | None) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        job.docs_status, job.docs_error = status, error
        session.add(job)
        session.commit()


def handler(event: dict, context) -> None:
    data_dir, engine, workspace = bootstrap()
    job_id = int(event["job_id"])
    options = event.get("options") or {}
    feedback, resume_id = options.get("feedback"), options.get("resume_id")
    try:
        try:
            generate_with_lock(data_dir, engine, build_deps(context), job_id, feedback, datetime.now(timezone.utc),
                               resume_id)
            _finish(engine, job_id, "ready", None)
        except RunInProgressError:
            _finish(engine, job_id, "error", IN_PROGRESS_COPY)
        except (DocsSetupError, StepNotConfiguredError, FileInUseError) as e:
            _finish(engine, job_id, "error", str(e))
        except Exception as e:
            log.exception("Writing documents failed")
            _finish(engine, job_id, "error", redact(friendly_message(e), _known_keys(data_dir)))
    finally:
        if workspace is not None:
            workspace.push()
        engine.dispose()
