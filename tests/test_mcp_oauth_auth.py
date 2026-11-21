import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from jobmecloud.api import routes_mcp
from jobmecloud.keys import store as keys
from jobmecloud.mcp import registry
from jobmecloud.oauth import store as oauth

SITE = "https://site.example"
VERIFIER = "v" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
REDIRECT = "https://chatgpt.com/cb"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_SITE_URL", SITE)
    saved = dict(registry.TOOLS)
    routes_mcp.reset_limits()

    @registry.tool("echo", "Echo text back.", {"type": "object", "properties": {"text": {"type": "string"}}})
    def echo(ctx, args):
        return {"said": args.get("text", "")}

    @registry.tool("change", "Pretend to change something.", {"type": "object"}, write=True)
    def change(ctx, args):
        return {"changed": True}

    yield
    registry.TOOLS.clear()
    registry.TOOLS.update(saved)


def connect(client, scope="read", age=timedelta(0)):
    """An OAuth connection made `age` ago; returns its tokens."""
    now = datetime.now(timezone.utc) - age
    with Session(client.app.state.engine) as s:
        app = oauth.register_client(s, name="ChatGPT", redirect_uris=[REDIRECT], now=now)
        code = oauth.issue_code(s, client=app, redirect_uri=REDIRECT, code_challenge=CHALLENGE, scope=scope, now=now)
        return oauth.exchange_code(s, client_id=app.client_id, code=code, redirect_uri=REDIRECT, verifier=VERIFIER, now=now)


def rpc(client, token, method, params=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=headers)


def call(client, token, name, args=None):
    r = rpc(client, token, "tools/call", {"name": name, "arguments": args or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_oauth_token_works_like_a_key(client):
    tokens = connect(client)
    assert rpc(client, tokens.access_token, "tools/list").status_code == 200
    result = call(client, tokens.access_token, "echo", {"text": "hi"})
    assert json.loads(result["content"][0]["text"]) == {"said": "hi"}


def test_read_grant_cannot_use_write_tools_but_readwrite_can(client):
    ro, rw = connect(client, "read"), connect(client, "readwrite")
    refused = call(client, ro.access_token, "change")
    assert refused["isError"] is True and "read-only" in refused["content"][0]["text"]
    assert call(client, rw.access_token, "change")["isError"] is False


def test_expired_access_token_gets_401_invalid_token(client):
    tokens = connect(client, age=timedelta(minutes=61))
    r = rpc(client, tokens.access_token, "ping")
    assert r.status_code == 401
    header = r.headers["www-authenticate"]
    assert 'error="invalid_token"' in header
    assert f'resource_metadata="{SITE}/.well-known/oauth-protected-resource/api/mcp"' in header


def test_no_token_gets_401_with_metadata_but_no_error(client):
    r = rpc(client, None, "ping")
    assert r.status_code == 401 and r.content == b""
    header = r.headers["www-authenticate"]
    assert header.startswith("Bearer ") and "error=" not in header
    assert f'resource_metadata="{SITE}/.well-known/oauth-protected-resource/api/mcp"' in header


def test_revoked_connection_gets_401(client):
    tokens = connect(client)
    with Session(client.app.state.engine) as s:
        key = keys.verify_key(s, tokens.access_token, datetime.now(timezone.utc))
        keys.revoke_key(s, key.id, datetime.now(timezone.utc))
    r = rpc(client, tokens.access_token, "ping")
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_desktop_keys_are_unchanged(client):
    with Session(client.app.state.engine) as s:
        _, good = keys.create_key(s, name="Desktop", scope="read", expires_at=None, now=datetime.now(timezone.utc))
        _, old = keys.create_key(s, name="Old", scope="read", expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                                 now=datetime.now(timezone.utc) - timedelta(days=2))
    assert rpc(client, good, "ping").status_code == 200
    assert rpc(client, old, "ping").status_code == 401


def test_401_still_works_when_site_url_is_not_set(client, monkeypatch):
    monkeypatch.delenv("JOBMECLOUD_SITE_URL")
    r = rpc(client, "jmc_nope", "ping")
    assert r.status_code == 401 and "www-authenticate" not in r.headers
