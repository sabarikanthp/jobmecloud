from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.db.models import Contact, FollowUp, Job
from jobmecloud.jobs import followups as fu_rules
from jobmecloud.jobs.tracking import TrackingError, local_date

router = APIRouter()

MISSING_COPY = "No follow-up with that id"
Bucket = Literal["overdue", "today", "upcoming", "done"]
_ORDER = {"overdue": 0, "today": 1, "upcoming": 2, "done": 3}


class FollowUpIn(BaseModel):
    type: str
    due_date: date
    job_id: int | None = None
    contact_id: int | None = None
    note: str | None = None


class DoneIn(BaseModel):
    outcome_note: str | None = None


class SnoozeIn(BaseModel):
    until: date


class RescheduleIn(BaseModel):
    due_date: date


class FollowUpRow(BaseModel):
    id: int
    job_id: int | None
    contact_id: int | None
    type: str
    due_date: str
    status: str
    bucket: Bucket
    note: str | None
    outcome_note: str | None
    completed_date: str | None
    employer: str | None
    job_title: str | None
    contact_name: str | None


def _today(request: Request) -> date:
    return request.app.state.today()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(session: Session, fu: FollowUp, today: date) -> FollowUpRow:
    contact = session.get(Contact, fu.contact_id) if fu.contact_id else None
    job = session.get(Job, fu.job_id) if fu.job_id else None
    if job is None and contact is not None and contact.job_id:
        job = session.get(Job, contact.job_id)
    done = local_date(fu.completed_at)
    return FollowUpRow(
        id=fu.id, job_id=fu.job_id, contact_id=fu.contact_id, type=fu.type,
        due_date=fu.due_date.isoformat(), status=fu.status, bucket=fu_rules.bucket(fu, today),
        note=fu.note, outcome_note=fu.outcome_note,
        completed_date=done.isoformat() if done else None,
        employer=job.employer if job else None, job_title=job.title if job else None,
        contact_name=contact.name if contact else None,
    )


def _commit(session: Session, fu: FollowUp, today: date) -> FollowUpRow:
    session.commit()
    session.refresh(fu)
    return _row(session, fu, today)


@router.get("/followups")
def list_followups(request: Request, bucket: Bucket | None = None, job_id: int | None = None,
                   contact_id: int | None = None) -> list[FollowUpRow]:
    today = _today(request)
    with Session(request.app.state.engine) as session:
        query = select(FollowUp)
        if job_id is not None:
            query = query.where(FollowUp.job_id == job_id)
        if contact_id is not None:
            query = query.where(FollowUp.contact_id == contact_id)
        rows = [(fu, fu_rules.bucket(fu, today)) for fu in session.exec(query)]
        if bucket is not None:
            rows = [r for r in rows if r[1] == bucket]

        def key(r):
            fu, b = r
            if b == "done":
                done = local_date(fu.completed_at) or date.min
                return (_ORDER[b], -done.toordinal(), fu.id)
            return (_ORDER[b], fu.due_date.toordinal(), fu.id)

        rows.sort(key=key)
        return [_row(session, fu, today) for fu, _ in rows]


@router.get("/followups/counts")
def counts(request: Request) -> dict:
    """How many follow-ups need attention: overdue, and due today. Used for the number in the menu."""
    today = _today(request)
    tally = {"overdue": 0, "due_today": 0}
    with Session(request.app.state.engine) as session:
        for fu in session.exec(select(FollowUp)):
            where = fu_rules.bucket(fu, today)
            if where == "overdue":
                tally["overdue"] += 1
            elif where == "today":
                tally["due_today"] += 1
    return tally


@router.post("/followups", status_code=201)
def create(body: FollowUpIn, request: Request) -> FollowUpRow:
    today = _today(request)
    with Session(request.app.state.engine) as session:
        try:
            fu = fu_rules.create_followup(session, type=body.type, due=body.due_date, at=_now(),
                                          job_id=body.job_id, contact_id=body.contact_id,
                                          note=body.note)
        except TrackingError as e:
            session.rollback()
            raise HTTPException(400, str(e))
        return _commit(session, fu, today)


def _act(request: Request, followup_id: int, action) -> FollowUpRow:
    today = _today(request)
    with Session(request.app.state.engine) as session:
        fu = session.get(FollowUp, followup_id)
        if fu is None:
            raise HTTPException(404, MISSING_COPY)
        try:
            action(session, fu, today)
        except TrackingError as e:
            session.rollback()
            raise HTTPException(400, str(e))
        return _commit(session, fu, today)


@router.post("/followups/{followup_id}/done")
def done(followup_id: int, request: Request, body: DoneIn | None = None) -> FollowUpRow:
    note = body.outcome_note if body else None
    return _act(request, followup_id,
                lambda s, fu, t: fu_rules.complete(s, fu, at=_now(), outcome_note=note))


@router.post("/followups/{followup_id}/snooze")
def snooze(followup_id: int, body: SnoozeIn, request: Request) -> FollowUpRow:
    return _act(request, followup_id,
                lambda s, fu, t: fu_rules.snooze(s, fu, until=body.until, today=t, at=_now()))


@router.post("/followups/{followup_id}/reschedule")
def reschedule(followup_id: int, body: RescheduleIn, request: Request) -> FollowUpRow:
    return _act(request, followup_id,
                lambda s, fu, t: fu_rules.reschedule(s, fu, due=body.due_date, today=t, at=_now()))


@router.post("/followups/{followup_id}/cancel")
def cancel(followup_id: int, request: Request) -> FollowUpRow:
    return _act(request, followup_id, lambda s, fu, t: fu_rules.cancel(s, fu, at=_now()))
