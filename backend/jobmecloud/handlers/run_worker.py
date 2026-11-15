"""Lambda entry point for search runs: started by the API ("Run now") or by EventBridge Scheduler."""

import logging
from datetime import datetime, timezone

from jobmecloud.agents.jobscout.pipeline import (
    RunDeps,
    RunSetupError,
    execute_run,
    preflight,
    record_failed_run,
    start_run,
)
from jobmecloud.handlers.common import bootstrap, time_is_short
from jobmecloud.jobs.runlock import RunInProgressError
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
            execute_run(data_dir, engine, run_id, deps, now)
    except Exception:
        # execute_run already recorded the failure on the Run. Do not re-raise: Lambda would retry the invoke.
        log.exception("Run failed")
    finally:
        if workspace is not None:
            workspace.push()
        engine.dispose()


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
