"""What happens when a report email reaches the mail bucket, up to handing the run to the worker.

Every email ends in a recorded outcome (an InboundEmail row), so nothing is lost silently, and the row is the
claim ticket: at most one invocation processes an email at a time, so a repeated or concurrent S3 notification
does nothing twice.
"""

import logging
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

log = logging.getLogger(__name__)
LOCK_POLL_SECONDS = 5
LOCK_WAIT_SECONDS = 480  # a documents job (up to 5 minutes) or a typical email run finishes inside this
MAX_RAW_BYTES = 2_000_000  # a report is a few thousand characters; anything this big is not one
DUPLICATE = "duplicate"
UNREADABLE_COPY = "The email could not be read from the mail bucket."
UNPARSEABLE_COPY = "The email could not be read: its contents were not a valid message."
TOO_LARGE_COPY = "The message is too large."
NOT_SENDER_COPY = "Not from the allowed sender."
LIMIT_COPY = "The daily limit for emailed reports was reached ({n}); this one was not run."
WAITING_COPY = "A run or documents job was in progress for too long; replay this email later with scripts/reprocess_email.py."
HANDOFF_COPY = "The run could not be handed to the worker."


def _ignore(engine: Engine, s3, bucket: str, key: str, email_id: int, note: str, sender: str | None = None) -> str:
    """Mail that is not from the owner's sender: delete it now and leave no trace on the Today screen."""
    store.set_status(engine, email_id, store.IGNORED, note=note, sender=sender)
    try:
        s3.delete_object(Bucket=bucket, Key=key)
    except Exception:
        log.warning("Could not delete ignored mail %s; the 30-day expiry will remove it", key)
    return store.IGNORED


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
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    reprocess: tuple[str, ...] = (),
) -> str:
    """Process one stored email and return its final status (or "duplicate" when it was already handled).

    `reprocess` names finished statuses that may be run again (the replay script passes `waiting` or `failed`).
    A row still in `received` is always retried (a previous attempt died before deciding anything), and a
    `processing` row whose claim has gone stale is taken over.
    """
    existing = store.get_by_key(engine, key)
    if existing is not None and existing.status not in (store.RECEIVED, store.PROCESSING, *reprocess):
        return DUPLICATE

    # Record it before looking inside: whatever happens next, the email has a row to show for it.
    email_id = existing.id if existing else store.record_received(engine, key, None, now)
    if email_id is None or not store.claim(engine, email_id, (store.RECEIVED, *reprocess), now):
        return DUPLICATE  # another delivery of the same object has it

    try:
        size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    except Exception:
        store.set_status(engine, email_id, store.FAILED, note=UNREADABLE_COPY)
        return store.FAILED
    if size > MAX_RAW_BYTES:  # decided before reading, so a stranger cannot make this function load a huge message
        return _ignore(engine, s3, bucket, key, email_id, TOO_LARGE_COPY)
    try:
        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:
        store.set_status(engine, email_id, store.FAILED, note=UNREADABLE_COPY)
        return store.FAILED
    try:
        email = parse_email(raw)
    except Exception:
        store.set_status(engine, email_id, store.FAILED, note=UNPARSEABLE_COPY)
        return store.FAILED
    if email.sender.lower() != config.sender.lower():  # anyone but the owner's sender: not a report at all
        return _ignore(engine, s3, bucket, key, email_id, NOT_SENDER_COPY, sender=email.sender or None)
    store.set_status(engine, email_id, store.PROCESSING, sender=email.sender)

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
