"""Job status rules and the Activity Log writer.

log, change_status and reopen never commit: they mutate, add and flush; the caller commits.
"""

from collections.abc import Sequence
from datetime import date, datetime, time, timezone, tzinfo
from typing import Literal

from sqlmodel import Session

from jobmecloud.db.models import ActivityLog, Job
from jobmecloud.jobs.actor import resolve

OPEN = ("New", "Ready", "Applied", "Interviewing", "Offer")
USER_STATUSES = ("Applied", "Interviewing", "Offer", "Accepted", "Rejected", "Withdrawn", "Skipped", "Unavailable", "Duplicate")
SKIP_REASON_COPY = "Choose why you're skipping this job."
FUTURE_DATE_COPY = "That date is in the future."
DUPLICATE_COPY = "Pick the job this one repeats."
NOT_ALLOWED_COPY = "That change isn't available for a job that is {status}."

# What the user can do next, in order of preference. "Reopen" is an action, not a status.
_USER_NEXT = {
    "New": ["Applied", "Skipped", "Rejected", "Withdrawn", "Unavailable", "Duplicate"],
    "Ready": ["Applied", "Skipped", "Rejected", "Withdrawn", "Unavailable", "Duplicate"],
    "Closed": ["Applied", "Reopen", "Duplicate"],
    "Applied": ["Interviewing", "Offer", "Rejected", "Withdrawn", "Unavailable"],
    "Interviewing": ["Offer", "Rejected", "Withdrawn", "Unavailable"],
    "Offer": ["Accepted", "Rejected", "Withdrawn"],
    "Skipped": ["Reopen"],
    "Withdrawn": ["Reopen"],
    "Unavailable": ["Reopen"],  # set by hand when the job is gone or can't be pursued
    "Duplicate": ["Reopen"],  # set by hand: the same job as one already in the tracker
}
# What the system may do: target status -> statuses it may come from.
_SYSTEM_FROM = {"New": (), "Ready": ("New",), "Closed": ("New", "Ready")}

_RESPONSE = ("Interviewing", "Offer", "Accepted", "Rejected")
_OUTCOME = ("Accepted", "Rejected", "Withdrawn", "Skipped", "Unavailable", "Duplicate")


class TrackingError(Exception):
    """The message is user-facing copy."""


def utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def utc_date(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def _local_tz() -> tzinfo | None:
    """The zone for local calendar dates; None means the machine's own zone. Tests patch this."""
    return None


def local_date(dt: datetime | None) -> date | None:
    """The local calendar date of a real instant (naive values are UTC, as SQLite returns them)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_local_tz()).date()


def local_midnight(d: date) -> datetime:
    """The UTC instant at which local calendar day d begins."""
    tz = _local_tz()
    start = datetime.combine(d, time.min, tzinfo=tz) if tz is not None else datetime.combine(d, time.min).astimezone()
    return start.astimezone(timezone.utc)


def allowed_next(job: Job) -> list[str]:
    return list(_USER_NEXT.get(job.status, []))


def log(session: Session, *, entity_type: str, entity_id: int, job_id: int | None, action: str,
        at: datetime, actor: str = "user", from_value: str | None = None,
        to_value: str | None = None, note: str | None = None) -> ActivityLog:
    row = ActivityLog(entity_type=entity_type, entity_id=entity_id, job_id=job_id, action=action,
                      from_value=from_value, to_value=to_value, at=at, actor=resolve(actor), note=note)
    session.add(row)
    session.flush()
    return row


def _original(session: Session, job: Job, duplicate_of: int | None) -> Job:
    """The job this one repeats: it must exist and not be this job, and a repeat of a repeat points at the first."""
    target = session.get(Job, duplicate_of) if duplicate_of is not None else None
    if target is None or target.id == job.id:
        raise TrackingError(DUPLICATE_COPY)
    seen = {job.id, target.id}
    while target.status == "Duplicate" and target.repost_of_id and target.repost_of_id not in seen:
        seen.add(target.repost_of_id)
        target = session.get(Job, target.repost_of_id) or target
    if target.id == job.id:
        raise TrackingError(DUPLICATE_COPY)
    return target


def change_status(session: Session, job: Job, to: str, *, actor: Literal["user", "system"], at: datetime,
                  on: date | None = None, skip_reason: str | None = None, skip_note: str | None = None,
                  note: str | None = None, skip_reasons: Sequence[str] = (), duplicate_of: int | None = None) -> None:
    if actor == "system":
        if to not in _SYSTEM_FROM or job.status not in _SYSTEM_FROM[to]:
            return
    else:
        if to not in USER_STATUSES or to not in allowed_next(job):
            raise TrackingError(NOT_ALLOWED_COPY.format(status=job.status))
        if to == "Skipped":
            reason = (skip_reason or "").strip()
            if not reason or (skip_reasons and skip_reason not in skip_reasons):
                raise TrackingError(SKIP_REASON_COPY)
        today = at.astimezone().date()
        on = on or today
        if on > today:
            raise TrackingError(FUTURE_DATE_COPY)
        if to == "Duplicate":
            original = _original(session, job, duplicate_of)

    old = job.status
    job.status = to
    if actor == "user":
        when = utc_midnight(on)
        if to == "Applied":
            job.applied_at = when
        if to in _RESPONSE and job.first_response_at is None and job.applied_at is not None:
            job.first_response_at = when
        if to in _OUTCOME:
            job.outcome_at = when
        if to == "Skipped":
            job.skip_reason = skip_reason
            job.skip_note = skip_note
        if to == "Duplicate":
            job.repost_of_id = original.id
    session.add(job)
    log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="status_changed",
        at=at, actor=actor, from_value=old, to_value=to, note=note)


def reopen(session: Session, job: Job, *, at: datetime, note: str | None = None) -> None:
    if job.status not in ("Skipped", "Withdrawn", "Closed", "Unavailable", "Duplicate"):
        raise TrackingError(NOT_ALLOWED_COPY.format(status=job.status))
    old = job.status
    job.status = "Ready" if job.docs_folder else "New"
    if old == "Duplicate":
        job.repost_of_id = None
    job.skip_reason = None
    job.skip_note = None
    job.outcome_at = None
    session.add(job)
    log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="reopened",
        at=at, actor="user", from_value=old, to_value=job.status, note=note)
