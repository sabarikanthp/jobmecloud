"""The record of every emailed report: what arrived, and what became of it."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from jobmecloud.db.models import InboundEmail
from jobmecloud.db.retry import retry_on_conflict

RECEIVED, STARTED, REJECTED, SKIPPED, WAITING, DONE, FAILED = (
    "received", "started", "rejected", "skipped", "waiting", "done", "failed")


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
def set_status(engine: Engine, email_id: int, status: str, *, run_id: int | None = None, note: str | None = None) -> None:
    with Session(engine) as session:
        row = session.get(InboundEmail, email_id)
        row.status = status
        if run_id is not None:
            row.run_id = run_id
        if note is not None:
            row.note = note
        session.add(row)
        session.commit()


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
