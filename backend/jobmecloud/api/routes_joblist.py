from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func
from sqlmodel import Session, select

from jobmecloud.db.models import Job
from jobmecloud.jobs import views

router = APIRouter()

MISSING_COPY = "No job with that id"


def _pairs(raw: list[str] | None) -> list[tuple[int, str]]:
    """`cf=<field id>:<value>` filters; a malformed one is ignored."""
    out = []
    for item in raw or []:
        head, sep, value = item.partition(":")
        if sep and head.strip().isdigit():
            out.append((int(head), value))
    return out


@router.get("/jobs")
def list_jobs(
    request: Request,
    status: Annotated[list[str] | None, Query()] = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    q: str | None = None,
    source: str | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to_: Annotated[date | None, Query(alias="to")] = None,
    flag: str | None = None,
    has_followup: bool | None = None,
    sort: Annotated[str, Query(pattern=r"^(first_seen|match|employer|status|applied|field:\d+)$")] = "first_seen",
    fields: Annotated[list[int] | None, Query()] = None,
    cf: Annotated[list[str] | None, Query()] = None,
    dir: Literal["asc", "desc"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    direction = dir or ("asc" if sort == "employer" else "desc")
    with Session(request.app.state.engine) as session:
        total, rows = views.list_jobs(
            session, status=status, min_score=min_score, q=q, source=source, from_=from_, to_=to_,
            flag=flag, has_followup=has_followup, sort=sort, direction=direction, limit=limit,
            offset=offset, fields=fields, cf=_pairs(cf))
        return {"total": total, "rows": rows}


@router.get("/jobs/facets")
def facets(request: Request) -> dict:
    with Session(request.app.state.engine) as session:
        sources = session.exec(select(Job.source).where(Job.source.is_not(None)).distinct()).all()
        counts = session.exec(select(Job.status, func.count()).group_by(Job.status)).all()
    return {"sources": sorted((s for s in sources if s), key=lambda s: (s.lower(), s)),
            "statuses": {status: n for status, n in counts}}


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, request: Request) -> dict:
    with Session(request.app.state.engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, MISSING_COPY)
        return views.job_detail(session, job, request.app.state.today())
