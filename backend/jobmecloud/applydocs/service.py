"""Write the documents for one job, holding the run lock so a search and a rewrite never touch the same files."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine

from jobmecloud.agents.jobscout.pipeline import RunDeps
from jobmecloud.applydocs.make_docs import DocsResult, make_docs
from jobmecloud.config.settings import load_settings
from jobmecloud.jobs.runlock import acquire_run_lock, lock_heartbeat, release_run_lock
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.steps import provider_for_step


def generate_with_lock(
    data_dir: Path, engine: Engine, deps: RunDeps, job_id: int, feedback: str | None, now: datetime
) -> DocsResult:
    """Raises RunInProgressError, DocsSetupError, StepNotConfiguredError, FileInUseError or a provider error."""
    owner = acquire_run_lock(engine, now)
    try:
        with lock_heartbeat(engine, owner):
            settings = load_settings(data_dir)
            provider, model = provider_for_step(settings, "tailor", deps.provider_builder)
            costs = CostTracker(settings.prices, settings.caps.max_spend_per_run_usd)
            return make_docs(
                data_dir, engine, job_id, provider=provider, model=model, costs=costs,
                counter=deps.page_counter, now=now, feedback=feedback,
            )
    finally:
        release_run_lock(engine, owner)
