import base64
import hashlib
import json
import logging
from urllib.parse import parse_qs, urlparse

import pytest

from jobmecloud.api import routes_mcp, routes_oauth

SITE = "https://site.example"
REDIRECT = "https://chatgpt.com/cb"
VERIFIER = "v" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_SITE_URL", SITE)
    routes_oauth.reset_limits()
    routes_mcp.reset_limits()


def register(client):
    return client.post("/api/oauth/register", json={"client_name": "ChatGPT", "redirect_uris": [REDIRECT]}).json()["client_id"]


def approve(client, cid, scope="read", approve=True, **overrides):
    body = {"client_id": cid, "redirect_uri": REDIRECT, "state": "st", "code_challenge": CHALLENGE, "scope": scope,
            "approve": approve, **overrides}
    return client.post("/api/oauth/approve", json=body)


def code_from(response) -> str:
    return parse_qs(urlparse(response.json()["redirect_to"]).query)["code"][0]


def token(client, **form):
    return client.post("/api/oauth/token", data=form)


def exchange(client, cid, code, verifier=VERIFIER, redirect=REDIRECT):
    return token(client, grant_type="authorization_code", client_id=cid, code=code, redirect_uri=redirect, code_verifier=verifier)


def mcp(client, access, method="tools/list"):
    return client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method},
                       headers={"Authorization": f"Bearer {access}"})


def test_full_flow_then_mcp_call(client):
    cid = register(client)
    consent = client.get("/api/oauth/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "state": "st",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256"}, follow_redirects=False)
    assert consent.status_code == 302
    assert client.get(f"/api/oauth/clients/{cid}").json() == {"name": "ChatGPT", "redirect_hosts": ["chatgpt.com"]}
    approved = approve(client, cid)
    redirect_to = urlparse(approved.json()["redirect_to"])
    assert f"{redirect_to.scheme}://{redirect_to.netloc}{redirect_to.path}" == REDIRECT
    assert parse_qs(redirect_to.query)["state"] == ["st"]
    r = exchange(client, cid, code_from(approved))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    first = r.json()
    assert first["token_type"] == "Bearer" and first["expires_in"] == 3600 and first["scope"] == "read"
    assert mcp(client, first["access_token"]).status_code == 200
    second = token(client, grant_type="refresh_token", client_id=cid, refresh_token=first["refresh_token"]).json()
    assert second["access_token"] != first["access_token"]
    assert mcp(client, first["access_token"]).status_code == 401
    assert mcp(client, second["access_token"]).status_code == 200
    stale = token(client, grant_type="refresh_token", client_id=cid, refresh_token=first["refresh_token"])
    assert stale.status_code == 400 and stale.json()["error"] == "invalid_grant"


def test_scope_is_what_the_owner_chose(client):
    cid = register(client)
    r = exchange(client, cid, code_from(approve(client, cid, scope="read")))
    assert r.json()["scope"] == "read"
    rw = exchange(client, cid, code_from(approve(client, cid, scope="readwrite"))).json()
    assert rw["scope"] == "readwrite"


def test_deny_returns_access_denied(client):
    cid = register(client)
    query = parse_qs(urlparse(approve(client, cid, approve=False).json()["redirect_to"]).query)
    assert query["error"] == ["access_denied"] and query["state"] == ["st"] and "code" not in query


def test_approve_rejects_bad_scope_and_unregistered_redirect(client):
    cid = register(client)
    assert approve(client, cid, scope="admin").status_code == 422
    assert approve(client, cid, redirect_uri="https://evil.example/cb").status_code == 400
    assert approve(client, "nope").status_code == 400
    assert approve(client, cid, code_challenge="short").status_code == 400


def test_unknown_client_lookup_is_404(client):
    assert client.get("/api/oauth/clients/nope").status_code == 404


def test_token_rejects_wrong_verifier_and_reused_code_which_revokes(client):
    cid = register(client)
    assert exchange(client, cid, code_from(approve(client, cid)), verifier="w" * 50).json()["error"] == "invalid_grant"
    code = code_from(approve(client, cid))
    access = exchange(client, cid, code).json()["access_token"]
    again = exchange(client, cid, code)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    assert mcp(client, access).status_code == 401


def test_token_endpoint_input_errors(client):
    cid = register(client)
    assert token(client, grant_type="password", client_id=cid).json()["error"] == "unsupported_grant_type"
    assert token(client).json()["error"] == "invalid_request"
    assert client.post("/api/oauth/token", content=b"\xff\xfe", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 400
    assert token(client, grant_type="authorization_code", client_id=cid).json()["error"] == "invalid_request"


def test_token_ignores_resource_parameter(client):
    cid = register(client)
    r = token(client, grant_type="authorization_code", client_id=cid, code=code_from(approve(client, cid)),
              redirect_uri=REDIRECT, code_verifier=VERIFIER, resource=f"{SITE}/api/mcp")
    assert r.status_code == 200


def test_refresh_after_revoke_fails(client):
    cid = register(client)
    tokens = exchange(client, cid, code_from(approve(client, cid))).json()
    key = next(k for k in client.get("/api/keys").json() if k["name"].startswith("ChatGPT"))
    assert client.delete(f"/api/keys/{key['id']}").status_code == 204
    r = token(client, grant_type="refresh_token", client_id=cid, refresh_token=tokens["refresh_token"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert mcp(client, tokens["access_token"]).status_code == 401


def test_tokens_are_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    cid = register(client)
    code = code_from(approve(client, cid))
    tokens = exchange(client, cid, code).json()
    logged = caplog.text
    for secret in (code, tokens["access_token"], tokens["refresh_token"], VERIFIER):
        assert secret not in logged


def test_desktop_key_flow_still_works(client):
    created = client.post("/api/keys", json={"name": "Desktop", "scope": "read"}).json()
    assert mcp(client, created["key"]).status_code == 200
    assert json.loads(client.get("/api/keys").text)[0]["name"] == "Desktop"
