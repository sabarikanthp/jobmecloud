"""Create, list and revoke the API keys Claude Desktop uses. Behind the normal sign-in, never reachable with a key."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from sqlmodel import select

from jobmecloud.db.models import ApiKey, OAuthClient, OAuthGrant
from jobmecloud.keys import store

router = APIRouter()


class KeyIn(BaseModel):
    name: str
    scope: Literal["read", "readwrite"] = "read"
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A key needs a name.")
        return v[:60]


class KeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    via: Literal["key", "sign-in"] = "key"  # sign-in: made by approving a connector (ChatGPT, Claude) rather than by a key
    app_name: str | None = None


class KeyCreated(KeyOut):
    key: str  # shown once, here only


def _out(row: ApiKey, app_name: str | None = None, via: str = "key") -> dict:
    return KeyOut(id=row.id, name=row.name, prefix=row.prefix, scope=row.scope, created_at=row.created_at,
                  expires_at=row.expires_at, last_used_at=row.last_used_at, revoked_at=row.revoked_at,
                  via=via, app_name=app_name).model_dump()


@router.get("/keys")
def list_keys(request: Request) -> list[KeyOut]:
    with Session(request.app.state.engine) as session:
        app_by_key = {g.api_key_id: g.client_id for g in session.exec(select(OAuthGrant))}
        names = {c.client_id: c.name for c in session.exec(select(OAuthClient))}
        return [KeyOut(**_out(r, names.get(app_by_key.get(r.id)), "sign-in" if r.id in app_by_key else "key"))
                for r in store.list_keys(session)]


@router.post("/keys", status_code=201)
def create_key(body: KeyIn, request: Request) -> KeyCreated:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    with Session(request.app.state.engine) as session:
        row, key = store.create_key(session, name=body.name, scope=body.scope, expires_at=expires, now=now)
        return KeyCreated(**_out(row), key=key)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: int, request: Request) -> Response:
    with Session(request.app.state.engine) as session:
        if not store.revoke_key(session, key_id, datetime.now(timezone.utc)):
            raise HTTPException(404, "That key does not exist.")
    return Response(status_code=204)
