"""The record of every emailed report: what arrived, and what became of it."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from jobmecloud.db.models import InboundEmail
from jobmecloud.db.retry import retry_on_conflict

RECEIVED, PROCESSING, STARTED, REJECTED, SKIPPED, WAITING, DONE, FAILED, IGNORED = (
    "received", "processing", "started", "rejected", "skipped", "waiting", "done", "failed", "ignored")
STALE_CLAIM_SECONDS = 900  # longer than the ingest function can run, so only a crashed invocation goes stale


def get_by_key(engine: Engine, s3_key: str) -> InboundEmail | None:
    with Session(engine) as session:
        row = session.exec(select(InboundEmail).where(InboundEmail.s3_key == s3_key)).first()
        if row is not None:
            session.expunge(row)
        return row


@retry_on_conflict()
def record_received(engine: Engine, s3_key: str, sender: str | None, now: datetime) -> int | None:
    """Note a new email and return its id, or None when this object was already recorded (a repeat delivery)."""
    with Session(engine) as session:
        if session.exec(select(InboundEmail.id).where(InboundEmail.s3_key == s3_key)).first() is not None:
            return None
        row = InboundEmail(s3_key=s3_key, received_at=now, sender=sender, status=RECEIVED)
        session.add(row)
        try:
            session.commit()
        except IntegrityError:  # another delivery of the same object won the race
            session.rollback()
            return None
        return row.id


@retry_on_conflict()
def set_status(engine: Engine, email_id: int, status: str, *, run_id: int | None = None, note: str | None = None,
               sender: str | None = None) -> None:
    with Session(engine) as session:
        row = session.get(InboundEmail, email_id)
        row.status = status
        if sender is not None:
            row.sender = sender
        if run_id is not None:
            row.run_id = run_id
        if note is not None:
            row.note = note
        session.add(row)
        session.commit()


@retry_on_conflict()
def claim(engine: Engine, email_id: int, allowed: tuple[str, ...], now: datetime,
          stale_after_seconds: int = STALE_CLAIM_SECONDS) -> bool:
    """Take an email for processing, atomically: True for exactly one of any number of concurrent callers.

    It can be taken from one of the `allowed` statuses, or from `processing` when that claim has gone stale
    (the invocation that held it crashed).
    """
    table = InboundEmail.__table__
    cutoff = now - timedelta(seconds=stale_after_seconds)
    stale = and_(table.c.status == PROCESSING, table.c.claimed_at < cutoff)
    with engine.begin() as conn:
        result = conn.execute(update(table).where(table.c.id == email_id, or_(table.c.status.in_(allowed), stale))
                              .values(status=PROCESSING, claimed_at=now))
        return result.rowcount == 1


def started_today(engine: Engine, now: datetime) -> int:
    """Emails that began or finished a run on today's calendar date (in the computer's own time zone)."""
    today = now.astimezone().date()
    with Session(engine) as session:
        rows = session.exec(select(InboundEmail).where(
            InboundEmail.status.in_((STARTED, DONE)), InboundEmail.received_at >= now - timedelta(days=2))).all()
    return sum(1 for r in rows if _local_date(r.received_at) == today)


def _local_date(moment: datetime):
    """The calendar date of a stored moment. The database hands back UTC, possibly without a zone attached."""
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone().date()


def recent(engine: Engine, limit: int = 20, *, include_ignored: bool = False) -> list[InboundEmail]:
    """The newest emails first, so the owner can see what arrived and what became of it.

    Mail from anyone but the allowed sender is ignored and deleted; it is left out unless asked for.
    """
    query = select(InboundEmail).order_by(InboundEmail.received_at.desc(), InboundEmail.id.desc()).limit(limit)
    if not include_ignored:
        query = query.where(InboundEmail.status != IGNORED)
    with Session(engine) as session:
        rows = session.exec(query).all()
        for row in rows:
            session.expunge(row)
        return list(rows)
