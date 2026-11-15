"""Follow-up rules.

Every function here mutates, adds and flushes; none commits. The caller commits.
"""

from datetime import date, datetime, timedelta
from typing import Literal

from sqlmodel import Session, select

from jobmecloud.db.models import Contact, FollowUp, Job
from jobmecloud.jobs.tracking import TrackingError, log

FOLLOWUP_TYPES = ("Application check-in", "Recruiter outreach", "Thank-you note", "Referral request", "Other")
FOLLOWUP_STATUSES = ("Open", "Done", "Snoozed", "Cancelled")
PAST_DATE_COPY = "Pick today or a later date."
FINISHED_COPY = "That follow-up is already finished."
TARGET_COPY = "A follow-up needs a job or a contact."
TYPE_COPY = "Choose a type of follow-up."
NO_JOB_COPY = "That job no longer exists."
NO_CONTACT_COPY = "That contact no longer exists."
CHECK_IN ="Application check-in"


def bucket(fu: FollowUp, today: date) -> Literal["overdue", "today", "upcoming", "done"]:
    if fu.status in ("Done", "Cancelled"):
        return "done"
    if fu.due_date < today:
        return "overdue"
    if fu.due_date == today:
        return "today"
    return "upcoming"


def _log(session: Session, fu: FollowUp, action: str, at: datetime, *, actor: str = "user",
         from_value: str | None = None, to_value: str | None = None, note: str | None = None) -> None:
    job_id = fu.job_id
    if job_id is None and fu.contact_id is not None:
        contact = session.get(Contact, fu.contact_id)
        job_id = contact.job_id if contact else None
    log(session, entity_type="followup", entity_id=fu.id, job_id=job_id, action=action, at=at,
        actor=actor, from_value=from_value, to_value=to_value, note=note)


def create_followup(session: Session, *, type: str, due: date, at: datetime, job_id: int | None = None,
                    contact_id: int | None = None, note: str | None = None, actor: str = "user") -> FollowUp:
    if job_id is None and contact_id is None:
        raise TrackingError(TARGET_COPY)
    if type not in FOLLOWUP_TYPES:
        raise TrackingError(TYPE_COPY)
    if job_id is not None and session.get(Job, job_id) is None:
        raise TrackingError(NO_JOB_COPY)
    contact = session.get(Contact, contact_id) if contact_id is not None else None
    if contact_id is not None and contact is None:
        raise TrackingError(NO_CONTACT_COPY)
    if job_id is None and contact is not None and contact.job_id is not None:
        job_id = contact.job_id
    fu =FollowUp(job_id=job_id, contact_id=contact_id, type=type, due_date=due, status="Open",
                  created_at=at, note=note)
    session.add(fu)
    session.flush()
    _log(session, fu, "followup_created", at, actor=actor, to_value=due.isoformat(), note=note)
    return fu


def create_for_applied(session: Session, job: Job, *, default_days: int | None, applied_on: date,
                       at: datetime) -> FollowUp | None:
    if not default_days:
        return None
    existing = session.exec(
        select(FollowUp).where(FollowUp.job_id == job.id, FollowUp.type == CHECK_IN)
    ).first()
    if existing is not None:
        return None
    return create_followup(session, type=CHECK_IN, due=applied_on + timedelta(days=default_days),
                           at=at, job_id=job.id, actor="system")


def _open(fu: FollowUp) -> None:
    if fu.status in ("Done", "Cancelled"):
        raise TrackingError(FINISHED_COPY)


def complete(session: Session, fu: FollowUp, *, at: datetime, outcome_note: str | None = None) -> None:
    _open(fu)
    old = fu.status
    fu.status = "Done"
    fu.completed_at = at
    fu.outcome_note = outcome_note
    session.add(fu)
    _log(session, fu, "followup_done", at, from_value=old, to_value="Done", note=outcome_note)


def snooze(session: Session, fu: FollowUp, *, until: date, today: date, at: datetime) -> None:
    _open(fu)
    if until < today:
        raise TrackingError(PAST_DATE_COPY)
    old = fu.due_date
    fu.status = "Snoozed"
    fu.due_date = until
    session.add(fu)
    _log(session, fu, "followup_snoozed", at, from_value=old.isoformat(), to_value=until.isoformat(),
         note=fu.note)


def reschedule(session: Session, fu: FollowUp, *, due: date, today: date, at: datetime) -> None:
    _open(fu)
    if due < today:
        raise TrackingError(PAST_DATE_COPY)
    old = fu.due_date
    fu.status = "Open"
    fu.due_date = due
    session.add(fu)
    _log(session, fu, "followup_rescheduled", at, from_value=old.isoformat(), to_value=due.isoformat(),
         note=fu.note)


def cancel(session: Session, fu: FollowUp, *, at: datetime) -> None:
    _open(fu)
    old = fu.status
    fu.status = "Cancelled"
    session.add(fu)
    _log(session, fu, "followup_cancelled", at, from_value=old, to_value="Cancelled", note=fu.note)
