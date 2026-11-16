"""Lambda entry point for search runs: started by the API ("Run now") or by EventBridge Scheduler."""

import logging
import os
from datetime import datetime, timezone

import boto3

from jobmecloud.agents.jobscout.pipeline import (
    RunDeps,
    RunSetupError,
    abandon_run,
    execute_run,
    preflight,
    record_failed_run,
    start_run,
)
from jobmecloud.handlers.common import bootstrap, time_is_short
from jobmecloud.inbound import store
from jobmecloud.inbound.source import build_email_source
from jobmecloud.jobs.runlock import RunInProgressError
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.factory import build_provider

log = logging.getLogger(__name__)
SKIPPED_COPY = "Skipped: a run was already in progress."

__all__ = ["handler", "time_is_short", "build_deps"]


def build_deps(context) -> RunDeps:
    return RunDeps(provider_builder=build_provider, should_stop=lambda: time_is_short(context))


def handler(event: dict, context) -> None:
    data_dir, engine, workspace = bootstrap()
    deps = build_deps(context)
    now = datetime.now(timezone.utc)
    try:
        if event.get("task") == "run":
            run_id = int(event["run_id"])
        elif event.get("trigger") == "schedule":
            run_id = _start_scheduled(data_dir, engine, deps, now)
        else:
            log.error("Unknown run-worker event: %s", sorted(event))
            return
        if run_id is not None:
            if event.get("email_key"):
                _run_email(data_dir, engine, deps, run_id, event["email_key"], now)
            else:
                execute_run(data_dir, engine, run_id, deps, now)
    except Exception:
        # execute_run already recorded the failure on the Run. Do not re-raise: Lambda would retry the invoke.
        log.exception("Run failed")
    finally:
        if workspace is not None:
            workspace.push()
        engine.dispose()


def _mark_email(engine, key: str, status: str, note: str | None = None) -> None:
    row = store.get_by_key(engine, key)
    if row is not None:  # a replayed or hand-started run may have no record
        store.set_status(engine, row.id, status, note=note)


def _run_email(data_dir, engine, deps: RunDeps, run_id: int, key: str, now: datetime) -> None:
    """A run started by the ingest function: its candidates come from the stored email, not from a search."""
    try:
        preflight(data_dir, deps, needs_search=False)
    except RunSetupError as e:
        abandon_run(engine, run_id, str(e), now)  # the run was started, so close it and give the lock back
        _mark_email(engine, key, store.FAILED, str(e))
        return
    source = build_email_source(boto3.client("s3"), os.environ.get("JOBMECLOUD_INBOX_BUCKET"), key)
    try:
        execute_run(data_dir, engine, run_id, deps, now, source=source)
    except Exception as e:
        message = str(e) if isinstance(e, RunSetupError) else friendly_message(e)
        _mark_email(engine, key, store.FAILED, message[:500])
        raise
    _mark_email(engine, key, store.DONE)


def _start_scheduled(data_dir, engine, deps: RunDeps, now: datetime) -> int | None:
    try:
        preflight(data_dir, deps)
    except RunSetupError as e:
        record_failed_run(engine, "schedule", now, str(e))
        return None
    try:
        return start_run(engine, "schedule", now)
    except RunInProgressError:
        record_failed_run(engine, "schedule", now, SKIPPED_COPY)
        return None
