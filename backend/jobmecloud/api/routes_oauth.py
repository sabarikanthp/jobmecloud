"""OAuth sign-in for connectors (ChatGPT, Claude): the public discovery, registration and authorize routes.

Everything here is reachable without the owner's Cognito login on purpose (the connector has no login yet); each route
checks what it is given. Approving a connection and issuing tokens are in the same module further down, and the
approve call stays behind the normal sign-in.
"""

import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from jobmecloud.oauth import store

well_known = APIRouter()  # mounted at the site root: /.well-known/...
router = APIRouter()  # mounted under /api

SCOPES = ["read", "readwrite"]
REGISTER_PER_MINUTE = 10
MAX_REGISTER_BODY = 20_000  # bytes; a real registration is a few hundred
_registrations: deque = deque()


def reset_limits() -> None:
    _registrations.clear()


def _error(code: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": description}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _site() -> str | JSONResponse:
    try:
        return store.site_url()
    except store.OAuthError as e:
        return _error("server_error", e.description, 503)


@well_known.get("/.well-known/oauth-protected-resource/api/mcp")
@well_known.get("/.well-known/oauth-protected-resource")
def protected_resource() -> JSONResponse:
    site = _site()
    if isinstance(site, JSONResponse):
        return site
    return JSONResponse({"resource": f"{site}/api/mcp", "authorization_servers": [site],
                         "scopes_supported": SCOPES, "bearer_methods_supported": ["header"]})


@well_known.get("/.well-known/oauth-authorization-server")
def authorization_server() -> JSONResponse:
    site = _site()
    if isinstance(site, JSONResponse):
        return site
    return JSONResponse({
        "issuer": site,
        "authorization_endpoint": f"{site}/api/oauth/authorize",
        "token_endpoint": f"{site}/api/oauth/token",
        "registration_endpoint": f"{site}/api/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": SCOPES,
    })


def _too_many_registrations() -> bool:
    now = time.monotonic()
    while _registrations and now - _registrations[0] > 60:
        _registrations.popleft()
    if len(_registrations) >= REGISTER_PER_MINUTE:
        return True
    _registrations.append(now)
    return False


@router.post("/oauth/register")
async def register(request: Request) -> Response:
    if _too_many_registrations():
        return JSONResponse({"error": "temporarily_unavailable", "error_description": "Too many registrations."},
                            status_code=429, headers={"Retry-After": "60"})
    raw = await request.body()
    try:
        body = json.loads(raw or b"null") if len(raw) <= MAX_REGISTER_BODY else None
    except (ValueError, RecursionError):  # not JSON, or nested deeply enough to overflow the parser
        body = None
    if not isinstance(body, dict):
        return _error("invalid_client_metadata", "Send a JSON object with redirect_uris.")
    name = body.get("client_name")
    try:
        with Session(request.app.state.engine) as session:
            client = store.register_client(session, name=name if isinstance(name, str) else "",
                                           redirect_uris=body.get("redirect_uris"), now=datetime.now(timezone.utc))
            return JSONResponse({
                "client_id": client.client_id, "client_name": client.name, "redirect_uris": client.redirect_uris,
                "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            }, status_code=201, headers={"Cache-Control": "no-store"})
    except store.OAuthError as e:
        return _error(e.code, e.description)


def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query) + [(k, v) for k, v in params.items() if v is not None]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _bad_link() -> HTMLResponse:
    return HTMLResponse("<p>This sign-in link is not valid. Go back to the app and try connecting again.</p>", status_code=400)


@router.get("/oauth/authorize")
def authorize(request: Request) -> Response:
    q = request.query_params
    site = _site()
    if isinstance(site, JSONResponse):
        return site
    redirect_uri = q.get("redirect_uri", "")
    with Session(request.app.state.engine) as session:
        client = store.get_client(session, q.get("client_id", ""))
        if client is None or not redirect_uri or not store.check_redirect(client, redirect_uri):
            return _bad_link()  # never send the browser to an address nobody registered
    state = q.get("state")
    challenge = q.get("code_challenge", "")
    if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or not (43 <= len(challenge) <= 128):
        return Response(status_code=302, headers={"Location": _with_query(redirect_uri, error="invalid_request", state=state)})
    params = {"client_id": client.client_id, "redirect_uri": redirect_uri, "code_challenge": challenge}
    if state is not None:
        params["state"] = state
    if q.get("scope"):
        params["scope"] = q["scope"][:100]
    return Response(status_code=302, headers={"Location": f"{site}/#/connect?{urlencode(params)}"})


class ApproveIn(BaseModel):
    client_id: str
    redirect_uri: str
    state: str | None = None
    code_challenge: str
    scope: Literal["read", "readwrite"]
    approve: bool


@router.get("/oauth/clients/{client_id}")
def client_info(client_id: str, request: Request) -> Response:
    """What the consent page shows about the app asking. Owner-only (behind the normal sign-in)."""
    with Session(request.app.state.engine) as session:
        client = store.get_client(session, client_id)
        if client is None:
            return _error("invalid_client", "No such app.", 404)
        return JSONResponse({"name": client.name,
                             "redirect_hosts": sorted({urlsplit(u).hostname or "" for u in client.redirect_uris})})


@router.post("/oauth/approve")
def approve(body: ApproveIn, request: Request) -> Response:
    """The owner's answer on the consent page. Owner-only (behind the normal sign-in); returns where to send the browser."""
    now = datetime.now(timezone.utc)
    with Session(request.app.state.engine) as session:
        client = store.get_client(session, body.client_id)
        if client is None or not store.check_redirect(client, body.redirect_uri):
            return _error("invalid_request", "That connection request is not valid.")
        if not 43 <= len(body.code_challenge) <= 128:
            return _error("invalid_request", "That connection request is not valid.")
        if not body.approve:
            return JSONResponse({"redirect_to": _with_query(body.redirect_uri, error="access_denied", state=body.state)})
        code = store.issue_code(session, client=client, redirect_uri=body.redirect_uri,
                                code_challenge=body.code_challenge, scope=body.scope, now=now)
    return JSONResponse({"redirect_to": _with_query(body.redirect_uri, code=code, state=body.state)})


@router.post("/oauth/token")
async def token(request: Request) -> Response:
    try:
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8")).items()}
    except (UnicodeDecodeError, ValueError):
        return _error("invalid_request", "The request could not be read.")
    grant = form.get("grant_type")
    if not grant:
        return _error("invalid_request", "grant_type is required.")
    if grant == "authorization_code":
        needed = ("client_id", "code", "redirect_uri", "code_verifier")
    elif grant == "refresh_token":
        needed = ("client_id", "refresh_token")
    else:
        return _error("unsupported_grant_type", "Use authorization_code or refresh_token.")
    if not all(form.get(k) for k in needed):
        return _error("invalid_request", "Missing: " + ", ".join(k for k in needed if not form.get(k)))
    now = datetime.now(timezone.utc)
    try:
        with Session(request.app.state.engine) as session:
            if grant == "authorization_code":
                tokens = store.exchange_code(session, client_id=form["client_id"], code=form["code"],
                                             redirect_uri=form["redirect_uri"], verifier=form["code_verifier"], now=now)
            else:
                tokens = store.refresh(session, client_id=form["client_id"], refresh_token=form["refresh_token"], now=now)
    except store.OAuthError as e:
        return _error(e.code, e.description)
    return JSONResponse({"access_token": tokens.access_token, "token_type": "Bearer", "expires_in": tokens.expires_in,
                         "refresh_token": tokens.refresh_token, "scope": tokens.scope},
                        headers={"Cache-Control": "no-store"})
