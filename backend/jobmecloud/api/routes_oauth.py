"""OAuth sign-in for connectors (ChatGPT, Claude): the public discovery, registration and authorize routes.

Everything here is reachable without the owner's Cognito login on purpose (the connector has no login yet); each route
checks what it is given. Approving a connection and issuing tokens are in the same module further down, and the
approve call stays behind the normal sign-in.
"""

import json
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel import Session

from jobmecloud.oauth import store

well_known = APIRouter()  # mounted at the site root: /.well-known/...
router = APIRouter()  # mounted under /api

SCOPES = ["read", "readwrite"]
REGISTER_PER_MINUTE = 10
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
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
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
