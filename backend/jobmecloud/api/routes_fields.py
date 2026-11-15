from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.db.models import CustomField, CustomValue, Job
from jobmecloud.jobs import custom_fields as cf
from jobmecloud.jobs.tracking import TrackingError

router = APIRouter()

MISSING_JOB = "No job with that id"
MISSING_FIELD = "No field with that id"
TYPE_LOCKED = "A field's type can't be changed. Delete it and add a new one."


class FieldIn(BaseModel):
    name: str
    type: str
    choices: list[str] | None = None


class FieldPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    choices: list[str] | None = None
    position: int | None = None


class ValuesIn(BaseModel):
    values: dict[int, str | None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _out(session: Session, f: CustomField) -> dict:
    used = len(session.exec(select(CustomValue.id).where(CustomValue.field_id == f.id)).all())
    return {"id": f.id, "name": f.name, "type": f.type, "choices": list(f.choices),
            "position": f.position, "used": used}


def _field(session: Session, field_id: int) -> CustomField:
    f = session.get(CustomField, field_id)
    if f is None:
        raise HTTPException(404, MISSING_FIELD)
    return f


@router.get("/job-fields")
def list_fields(request: Request) -> list[dict]:
    with Session(request.app.state.engine) as session:
        return [_out(session, f) for f in cf.list_fields(session)]


@router.post("/job-fields")
def create_field(body: FieldIn, request: Request) -> dict:
    with Session(request.app.state.engine) as session:
        try:
            f = cf.create_field(session, name=body.name, type=body.type, choices=body.choices,
                                at=_now())
        except TrackingError as e:
            session.rollback()
            raise HTTPException(400, str(e))
        session.commit()
        session.refresh(f)
        return _out(session, f)


@router.patch("/job-fields/{field_id}")
def patch_field(field_id: int, body: FieldPatch, request: Request) -> dict:
    with Session(request.app.state.engine) as session:
        f = _field(session, field_id)
        if body.type is not None and body.type != f.type:
            raise HTTPException(400, TYPE_LOCKED)
        try:
            cf.update_field(session, f, name=body.name, choices=body.choices,
                            position=body.position, at=_now())
        except TrackingError as e:
            session.rollback()
            raise HTTPException(400, str(e))
        session.commit()
        session.refresh(f)
        return _out(session, f)


@router.delete("/job-fields/{field_id}")
def delete_field(field_id: int, request: Request) -> dict:
    with Session(request.app.state.engine) as session:
        f = _field(session, field_id)
        n = cf.delete_field(session, f)
        session.commit()
        return {"deleted_values": n}


@router.put("/jobs/{job_id}/fields")
def set_job_fields(job_id: int, body: ValuesIn, request: Request) -> dict:
    with Session(request.app.state.engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, MISSING_JOB)
        try:
            cf.set_values(session, job, body.values, at=_now())
        except TrackingError as e:
            session.rollback()
            raise HTTPException(400, str(e))
        session.commit()
        values = cf.values_for(session, [job_id]).get(job_id, {})
        return {"fields": {str(k): v for k, v in values.items()}}
