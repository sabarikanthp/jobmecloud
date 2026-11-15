from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from jobmecloud.config.settings import Day
from jobmecloud.db.models import WatchlistEmployer

router = APIRouter()

NAME_COPY = "Please enter the employer's name."
URL_COPY = "The careers page address should start with https://"
DUP_COPY = "That employer is already on your list."
MISSING_COPY = "No employer with that id"


class WatchlistIn(BaseModel):
    name: str
    priority: int = Field(default=2, ge=1, le=3)
    careers_url: str | None = None
    rotation_day: Day | None = None


def _row(e: WatchlistEmployer) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "priority": e.priority,
        "careers_url": e.careers_url,
        "rotation_day": e.rotation_day,
        "last_checked_at": e.last_checked_at,
    }


def _clean(body: WatchlistIn) -> tuple[str, str | None]:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, NAME_COPY)
    url = (body.careers_url or "").strip() or None
    if url is not None and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, URL_COPY)
    return name, url


def _check_duplicate(session: Session, name: str, own_id: int | None) -> None:
    query = select(WatchlistEmployer).where(
        func.lower(WatchlistEmployer.name) == name.lower()
    )
    for other in session.exec(query):
        if other.id != own_id:
            raise HTTPException(409, DUP_COPY)


@router.get("/watchlist")
def list_watchlist(request: Request) -> list[dict]:
    with Session(request.app.state.engine) as session:
        rows = session.exec(select(WatchlistEmployer)).all()
    rows.sort(key=lambda e: (e.priority, e.name.lower()))
    return [_row(e) for e in rows]


@router.post("/watchlist", status_code=201)
def add_employer(body: WatchlistIn, request: Request) -> dict:
    name, url = _clean(body)
    with Session(request.app.state.engine) as session:
        _check_duplicate(session, name, None)
        row = WatchlistEmployer(
            name=name, priority=body.priority, careers_url=url,
            rotation_day=body.rotation_day,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row(row)


@router.put("/watchlist/{employer_id}")
def update_employer(employer_id: int, body: WatchlistIn, request: Request) -> dict:
    name, url = _clean(body)
    with Session(request.app.state.engine) as session:
        row = session.get(WatchlistEmployer, employer_id)
        if row is None:
            raise HTTPException(404, MISSING_COPY)
        _check_duplicate(session, name, employer_id)
        row.name = name
        row.priority = body.priority
        row.careers_url = url
        row.rotation_day = body.rotation_day
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row(row)


@router.delete("/watchlist/{employer_id}", status_code=204)
def delete_employer(employer_id: int, request: Request) -> Response:
    with Session(request.app.state.engine) as session:
        row = session.get(WatchlistEmployer, employer_id)
        if row is None:
            raise HTTPException(404, MISSING_COPY)
        session.delete(row)
        session.commit()
    return Response(status_code=204)
