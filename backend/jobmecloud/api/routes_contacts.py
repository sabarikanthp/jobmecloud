from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.db.models import Contact, FollowUp, Interview, Job
from jobmecloud.jobs import followups as fu_rules
from jobmecloud.jobs import tracking
from jobmecloud.jobs.contacts import CONTACT_RELATIONSHIPS, CONTACT_STATUSES, NAME_COPY
from jobmecloud.jobs.tracking import TrackingError

router = APIRouter()

NO_CONTACT = "No contact with that id"
NO_INTERVIEW = "No interview with that id"
NO_JOB = "No job with that id"
LINK_COPY = "The link should start with https://"
DATE_COPY = "Enter the interview date as YYYY-MM-DD or YYYY-MM-DDTHH:MM."


class ContactIn(BaseModel):
    name: str = ""
    job_id: int | None = None
    employer: str | None = None
    role: str | None = None
    link: str | None = None
    relationship: str | None = None
    status: str | None = None
    notes: str | None = None


class ContactRow(BaseModel):
    id: int
    job_id: int | None
    employer: str | None
    name: str | None
    role: str | None
    link: str | None
    relationship: str | None
    status: str | None
    notes: str | None
    open_followups: int
    job_title: str | None


class InterviewIn(BaseModel):
    date: str | None = None
    stage: str | None = None
    notes: str | None = None


class InterviewOut(BaseModel):
    id: int
    job_id: int
    date: str | None
    stage: str | None
    notes: str | None
    status_changed: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _at(request: Request) -> datetime:
    today: date = request.app.state.today()
    return datetime.combine(today, datetime.now().time()).astimezone().astimezone(timezone.utc)


def _blank(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _row(session: Session, c: Contact) -> ContactRow:
    job = session.get(Job, c.job_id) if c.job_id else None
    open_n = len(session.exec(select(FollowUp).where(
        FollowUp.contact_id == c.id, FollowUp.status.in_(("Open", "Snoozed")))).all())
    return ContactRow(id=c.id, job_id=c.job_id, employer=c.employer, name=c.name, role=c.role,
                      link=c.link, relationship=c.relationship, status=c.status, notes=c.notes,
                      open_followups=open_n, job_title=job.title if job else None)


def _fill(session: Session, c: Contact, body: ContactIn) -> None:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, NAME_COPY)
    relationship, status, link = _blank(body.relationship), _blank(body.status), _blank(body.link)
    if relationship is not None and relationship not in CONTACT_RELATIONSHIPS:
        raise HTTPException(400, "Choose a relationship: " + ", ".join(CONTACT_RELATIONSHIPS) + ".")
    if status is not None and status not in CONTACT_STATUSES:
        raise HTTPException(400, "Choose a status: " + ", ".join(CONTACT_STATUSES) + ".")
    if link is not None and not link.lower().startswith(("http://", "https://")):
        raise HTTPException(400, LINK_COPY)
    job = None
    if body.job_id is not None:
        job = session.get(Job, body.job_id)
        if job is None:
            raise HTTPException(404, NO_JOB)
    c.name, c.job_id, c.role, c.link = name, body.job_id, _blank(body.role), link
    c.relationship, c.status, c.notes = relationship, status, _blank(body.notes)
    c.employer = _blank(body.employer) or (job.employer if job else None)


@router.get("/contacts")
def list_contacts(request: Request, job_id: int | None = None, q: str | None = None) -> list[ContactRow]:
    with Session(request.app.state.engine) as session:
        query = select(Contact).order_by(Contact.id.desc())
        if job_id is not None:
            query = query.where(Contact.job_id == job_id)
        rows = session.exec(query).all()
        needle = (q or "").strip().lower()
        if needle:
            rows = [c for c in rows if needle in " ".join(
                x for x in (c.name, c.employer, c.role, c.notes) if x).lower()]
        return [_row(session, c) for c in rows]


@router.post("/contacts", status_code=201)
def create_contact(body: ContactIn, request: Request) -> ContactRow:
    with Session(request.app.state.engine) as session:
        c = Contact()
        _fill(session, c, body)
        session.add(c)
        session.flush()
        tracking.log(session, entity_type="contact", entity_id=c.id, job_id=c.job_id,
                     action="contact_added", at=_now())
        session.commit()
        session.refresh(c)
        return _row(session, c)


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactIn, request: Request) -> ContactRow:
    with Session(request.app.state.engine) as session:
        c = session.get(Contact, contact_id)
        if c is None:
            raise HTTPException(404, NO_CONTACT)
        old = c.status
        _fill(session, c, body)
        session.add(c)
        changed = old != c.status
        tracking.log(session, entity_type="contact", entity_id=c.id, job_id=c.job_id,
                     action="contact_updated", at=_now(),
                     from_value=old if changed else None, to_value=c.status if changed else None)
        session.commit()
        session.refresh(c)
        return _row(session, c)


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, request: Request) -> None:
    at = _now()
    with Session(request.app.state.engine) as session:
        c = session.get(Contact, contact_id)
        if c is None:
            raise HTTPException(404, NO_CONTACT)
        for fu in session.exec(select(FollowUp).where(FollowUp.contact_id == c.id)).all():
            if fu.status in ("Open", "Snoozed"):
                fu_rules.cancel(session, fu, at=at)
            fu.contact_id = None
            session.add(fu)
        session.flush()
        tracking.log(session, entity_type="contact", entity_id=c.id, job_id=c.job_id,
                     action="contact_deleted", at=at)
        session.delete(c)
        session.commit()


def _parse_date(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        if len(value) == 10:
            local = datetime.combine(date.fromisoformat(value), datetime.min.time())
        else:
            local = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, DATE_COPY)
    if local.tzinfo is None:
        local = local.astimezone()  # naive means the server's local time
    return local.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _interview_out(i: Interview, changed: bool) -> InterviewOut:
    return InterviewOut(id=i.id, job_id=i.job_id, date=_iso(i.date), stage=i.stage, notes=i.notes,
                        status_changed=changed)


@router.post("/jobs/{job_id}/interviews", status_code=201)
def add_interview(job_id: int, body: InterviewIn, request: Request) -> InterviewOut:
    at = _at(request)
    with Session(request.app.state.engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, NO_JOB)
        when = _parse_date(body.date)
        i = Interview(job_id=job_id, date=when, stage=_blank(body.stage), notes=_blank(body.notes))
        session.add(i)
        session.flush()
        tracking.log(session, entity_type="interview", entity_id=i.id, job_id=job_id,
                     action="interview_added", at=at, to_value=i.stage)
        changed = False
        if job.status == "Applied":
            try:
                tracking.change_status(session, job, "Interviewing", actor="user", at=at)
            except TrackingError as e:
                session.rollback()
                raise HTTPException(400, str(e))
            changed = True
        session.commit()
        session.refresh(i)
        return _interview_out(i, changed)


@router.put("/interviews/{interview_id}")
def update_interview(interview_id: int, body: InterviewIn, request: Request) -> InterviewOut:
    with Session(request.app.state.engine) as session:
        i = session.get(Interview, interview_id)
        if i is None:
            raise HTTPException(404, NO_INTERVIEW)
        i.date, i.stage, i.notes = _parse_date(body.date), _blank(body.stage), _blank(body.notes)
        session.add(i)
        tracking.log(session, entity_type="interview", entity_id=i.id, job_id=i.job_id,
                     action="interview_updated", at=_now(), to_value=i.stage)
        session.commit()
        session.refresh(i)
        return _interview_out(i, False)


@router.delete("/interviews/{interview_id}", status_code=204)
def delete_interview(interview_id: int, request: Request) -> None:
    with Session(request.app.state.engine) as session:
        i = session.get(Interview, interview_id)
        if i is None:
            raise HTTPException(404, NO_INTERVIEW)
        tracking.log(session, entity_type="interview", entity_id=i.id, job_id=i.job_id,
                     action="interview_deleted", at=_now(), from_value=i.stage)
        session.delete(i)
        session.commit()
