from datetime import date, datetime, timezone
from datetime import date as Day
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.config.settings import load_settings
from jobmecloud.db.models import Job
from jobmecloud.jobs import followups as fu_rules
from jobmecloud.jobs import tracking
from jobmecloud.jobs.duplicates import find_duplicate
from jobmecloud.jobs.tracking import FUTURE_DATE_COPY, TrackingError, utc_date, utc_midnight

router = APIRouter()

MISSING_COPY = "No job with that id"
BLANK_COPY = "Please enter the employer and the job title."
LINK_COPY = "The link should start with https://"
DUPLICATE_COPY = "That job is already in JobMe."

Status = Literal["Applied", "Interviewing", "Offer", "Accepted", "Rejected", "Withdrawn", "Skipped", "Unavailable"]


class StatusIn(BaseModel):
    status: Status
    date: Day | None = None
    skip_reason: str | None = None
    skip_note: str | None = None
    note: str | None = None


class ReopenIn(BaseModel):
    note: str | None = None


class PatchIn(BaseModel):
    notes: str | None = None
    applied_date: date | None = None
    first_response_date: date | None = None
    outcome_date: date | None = None


class ManualJobIn(BaseModel):
    employer: str
    title: str
    apply_url: str | None = None
    location: str | None = None
    notes: str | None = None


class TrackingOut(BaseModel):
    id: int
    status: str
    applied_date: str | None
    first_response_date: str | None
    outcome_date: str | None
    allowed_next: list[str]
    follow_up_id: int | None


def _today(request: Request) -> date:
    return request.app.state.today()


def _at(request: Request) -> datetime:
    """Now, on the calendar day the app calls today (the server's own clock in normal use)."""
    return datetime.combine(_today(request), datetime.now().time()).astimezone().astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    d = utc_date(dt)
    return d.isoformat() if d else None


def _out(job: Job, follow_up_id: int | None = None) -> TrackingOut:
    return TrackingOut(
        id=job.id, status=job.status, applied_date=_iso(job.applied_at),
        first_response_date=_iso(job.first_response_at), outcome_date=_iso(job.outcome_at),
        allowed_next=tracking.allowed_next(job), follow_up_id=follow_up_id)


def _job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, MISSING_COPY)
    return job


@router.post("/jobs/{job_id}/status")
def set_status(job_id: int, body: StatusIn, request: Request) -> TrackingOut:
    settings = load_settings(request.app.state.data_dir)
    at = _at(request)
    with Session(request.app.state.engine) as session:
        job = _job(session, job_id)
        follow_up_id = None
        try:
            tracking.change_status(session, job, body.status, actor="user", at=at, on=body.date,
                                   skip_reason=body.skip_reason, skip_note=body.skip_note,
                                   note=body.note, skip_reasons=settings.skip_reasons)
            if body.status == "Applied":
                fu = fu_rules.create_for_applied(
                    session, job, default_days=settings.followup_default_days,
                    applied_on=utc_date(job.applied_at), at=at)
                follow_up_id = fu.id if fu else None
        except TrackingError as e:
            session.rollback()
            raise HTTPException(400, str(e))
        session.commit()
        session.refresh(job)
        return _out(job, follow_up_id)


@router.post("/jobs/{job_id}/reopen")
def reopen(job_id: int, request: Request, body: ReopenIn | None = None) -> TrackingOut:
    with Session(request.app.state.engine) as session:
        job = _job(session, job_id)
        try:
            tracking.reopen(session, job, at=_at(request), note=body.note if body else None)
        except TrackingError as e:
            session.rollback()
            raise HTTPException(400, str(e))
        session.commit()
        session.refresh(job)
        return _out(job)


@router.patch("/jobs/{job_id}")
def patch(job_id: int, body: PatchIn, request: Request) -> TrackingOut:
    today = _today(request)
    given = body.model_fields_set
    dates = {"applied_date": "applied_at", "first_response_date": "first_response_at",
             "outcome_date": "outcome_at"}
    with Session(request.app.state.engine) as session:
        job = _job(session, job_id)
        for field in dates:
            value = getattr(body, field)
            if field in given and value is not None and value > today:
                raise HTTPException(400, FUTURE_DATE_COPY)
        changed = []
        for field, column in dates.items():
            if field in given:
                value = getattr(body, field)
                setattr(job, column, utc_midnight(value) if value else None)
        if given & set(dates):
            changed.append("dates")
        if "notes" in given:
            job.notes = body.notes
            changed.append("notes")
        if changed:
            session.add(job)
            tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="edited",
                         at=_at(request), note=", ".join(changed))
        session.commit()
        session.refresh(job)
        return _out(job)


@router.post("/jobs", status_code=201)
def add_job(body: ManualJobIn, request: Request) -> dict:
    employer, title = body.employer.strip(), body.title.strip()
    if not employer or not title:
        raise HTTPException(400, BLANK_COPY)
    url = (body.apply_url or "").strip() or None
    source = None
    if url:
        try:
            parts = urlsplit(url)
        except ValueError:
            raise HTTPException(400, LINK_COPY)
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
            raise HTTPException(400, LINK_COPY)
        source = parts.hostname
    location = (body.location or "").strip() or None
    with Session(request.app.state.engine) as session:
        if find_duplicate(session, employer=employer, title=title, location=location,
                          requisition_id=None, url=url):
            raise HTTPException(409, DUPLICATE_COPY)
        at = _at(request)
        job = Job(employer=employer, title=title, apply_url=url, location=location,
                  notes=(body.notes or "").strip() or None, origin="manual", status="New",
                  first_seen_at=at, source=source, flags=[], hard_rules=[])
        session.add(job)
        session.flush()
        tracking.log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="added", at=at)
        session.commit()
        return {"id": job.id, "status": job.status}
