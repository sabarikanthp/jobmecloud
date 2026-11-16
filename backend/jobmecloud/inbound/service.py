"""What happens when a report email reaches the mail bucket, up to handing the run to the worker.

Every email ends in a recorded outcome (an InboundEmail row), so nothing is lost silently and a retry of the same
S3 notification does nothing twice.
"""

import time
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.engine import Engine

from jobmecloud.agents.jobscout.pipeline import abandon_run, start_run
from jobmecloud.inbound import store
from jobmecloud.inbound.parse import parse_email
from jobmecloud.inbound.trust import TrustConfig, check_trust
from jobmecloud.jobs.dispatch import Dispatcher
from jobmecloud.jobs.runlock import RunInProgressError

LOCK_POLL_SECONDS = 5
DUPLICATE = "duplicate"
UNREADABLE_COPY = "The email could not be read from the mail bucket."
LIMIT_COPY = "The daily limit for emailed reports was reached ({n}); this one was not run."
WAITING_COPY = "A run or documents job was in progress for too long; replay this email later with scripts/reprocess_email.py."
HANDOFF_COPY = "The run could not be handed to the worker."


def handle_email(
    engine: Engine,
    s3,
    dispatcher: Dispatcher,
    *,
    bucket: str,
    key: str,
    config: TrustConfig,
    daily_limit: int,
    now: datetime,
    lock_wait_seconds: float = 90,
    sleep: Callable[[float], None] = time.sleep,
    reprocess: tuple[str, ...] = (),
) -> str:
    """Process one stored email and return its final status (or "duplicate" when it was already handled).

    `reprocess` names finished statuses that may be run again (the replay script passes `waiting` or `failed`).
    A row still in `received` is always retried: a previous attempt died before deciding anything.
    """
    existing = store.get_by_key(engine, key)
    if existing is not None and existing.status not in (store.RECEIVED, *reprocess):
        return DUPLICATE

    try:
        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:
        email_id = existing.id if existing else store.record_received(engine, key, None, now)
        if email_id is not None:
            store.set_status(engine, email_id, store.FAILED, note=UNREADABLE_COPY)
        return store.FAILED

    email = parse_email(raw)
    email_id = existing.id if existing else store.record_received(engine, key, email.sender or None, now)
    if email_id is None:
        return DUPLICATE  # another delivery of the same object recorded it first

    reason = check_trust(email, config)
    if reason:
        store.set_status(engine, email_id, store.REJECTED, note=reason)
        return store.REJECTED
    if store.started_today(engine, now) >= daily_limit:
        store.set_status(engine, email_id, store.SKIPPED, note=LIMIT_COPY.format(n=daily_limit))
        return store.SKIPPED

    waited = 0.0
    while True:
        try:
            run_id = start_run(engine, "email", now)
            break
        except RunInProgressError:
            if waited >= lock_wait_seconds:
                store.set_status(engine, email_id, store.WAITING, note=WAITING_COPY)
                return store.WAITING
            sleep(LOCK_POLL_SECONDS)
            waited += LOCK_POLL_SECONDS

    store.set_status(engine, email_id, store.STARTED, run_id=run_id)
    try:
        dispatcher.start_run(run_id, email_key=key)
    except Exception:
        abandon_run(engine, run_id, HANDOFF_COPY, now)  # close the run and give the lock back
        store.set_status(engine, email_id, store.FAILED, note=HANDOFF_COPY)
        return store.FAILED
    return store.STARTED
