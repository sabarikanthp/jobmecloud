"""The door Claude Desktop uses. API Gateway does not sign-in check this one route; the key is checked here."""

import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from sqlmodel import Session

from jobmecloud.keys import store
from jobmecloud.oauth import store as oauth
from jobmecloud.mcp import protocol, tools_docs, tools_read, tools_write  # noqa: F401  (importing the tool modules registers the tools)

router = APIRouter()

RATE_PER_MINUTE = 60
AI_DAILY_LIMIT = 30
_recent: dict[int, deque] = defaultdict(deque)


def reset_limits() -> None:
    _recent.clear()


def _bearer(request: Request) -> str | None:
    parts = request.headers.get("authorization", "").split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _unauthorized(presented: str | None) -> Response:
    """401, with a pointer to the sign-in metadata so a connector can start (or restart) signing in."""
    try:
        return Response(status_code=401, headers={"WWW-Authenticate": oauth.www_authenticate(invalid_token=bool(presented))})
    except oauth.OAuthError:  # no site address configured: a bare 401, as for keys
        return Response(status_code=401)


def _too_fast(key_id: int) -> bool:
    """At most RATE_PER_MINUTE calls a minute per key (counted per running server instance: best effort)."""
    now = time.monotonic()
    window = _recent[key_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_PER_MINUTE:
        return True
    window.append(now)
    return False


@router.api_route("/mcp", methods=["GET", "DELETE"])
def not_supported() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
def mcp(message: dict, request: Request) -> Response:
    state = request.app.state
    now = datetime.now(timezone.utc)
    presented = _bearer(request)
    with Session(state.engine) as session:
        key = store.verify_key(session, presented, now) if presented else None
        if key is not None and presented.startswith(oauth.OAUTH_PREFIX) and not oauth.access_valid(session, key, now):
            key = None
        if key is None:
            return _unauthorized(presented)
        if _too_fast(key.id):
            return Response(status_code=429, headers={"Retry-After": "60"})
        store.touch(session, key, now)
        today = state.today()
        reply = protocol.handle(
            request.app, key, message, now=now, today=today,
            ai_allowed=lambda: store.spend_ai_call(session, key, today, AI_DAILY_LIMIT),
            host=request.headers.get("host"))
    if reply is None:
        return Response(status_code=202)
    return Response(content=json.dumps(reply), media_type="application/json")
