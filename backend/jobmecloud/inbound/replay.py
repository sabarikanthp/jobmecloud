"""Run a stored email again (for example one that was waiting for the run lock, or one that failed)."""

from datetime import datetime

from sqlalchemy.engine import Engine

from jobmecloud.inbound import store
from jobmecloud.inbound.service import handle_email
from jobmecloud.inbound.trust import TrustConfig
from jobmecloud.jobs.dispatch import Dispatcher

REPLAYABLE = (store.WAITING, store.FAILED)
EVERY_STATUS = (store.RECEIVED, store.STARTED, store.REJECTED, store.SKIPPED, store.WAITING, store.DONE, store.FAILED)


class ReplayRefused(Exception):
    """The email is in a state that should not be run again without saying so."""


def reprocess_email(engine: Engine, s3, dispatcher: Dispatcher, *, bucket: str, key: str, config: TrustConfig,
                    daily_limit: int, now: datetime, force: bool = False) -> str:
    row = store.get_by_key(engine, key)
    if row is not None and row.status not in REPLAYABLE and row.status != store.RECEIVED and not force:
        raise ReplayRefused(f"That email is '{row.status}'. Only waiting or failed emails are replayed; "
                            "pass --force to run it again anyway.")
    return handle_email(engine, s3, dispatcher, bucket=bucket, key=key, config=config, daily_limit=daily_limit,
                        now=now, reprocess=EVERY_STATUS if force else REPLAYABLE)
