def _create(client, **over):
    body = {"name": "Desktop", "scope": "read", "expires_in_days": None, **over}
    return client.post("/api/keys", json=body)


def test_create_then_list_never_returns_key_again(client):
    r = _create(client)
    assert r.status_code == 201
    key = r.json()["key"]
    assert key.startswith("jmc_")
    listed = client.get("/api/keys").json()
    assert len(listed) == 1
    assert "key" not in listed[0] and key not in client.get("/api/keys").text
    assert listed[0]["prefix"] == key[:8] and listed[0]["scope"] == "read"


def test_scope_validation_422(client):
    assert _create(client, scope="admin").status_code == 422


def test_revoke_marks_key_and_list_still_shows_it(client):
    kid = _create(client).json()["id"]
    assert client.delete(f"/api/keys/{kid}").status_code == 204
    row = client.get("/api/keys").json()[0]
    assert row["revoked_at"] is not None


def test_revoke_unknown_404(client):
    assert client.delete("/api/keys/999").status_code == 404


def test_name_required_and_trimmed(client):
    assert _create(client, name="   ").status_code == 422
    assert _create(client, name="  Laptop  ").json()["name"] == "Laptop"


def test_expiry_days_sets_expires_at(client):
    assert _create(client, expires_in_days=30).json()["expires_at"] is not None
    assert _create(client, expires_in_days=0).status_code == 422


def test_list_marks_sign_in_connections(client, monkeypatch):
    import base64
    import hashlib
    from datetime import datetime, timezone

    from sqlmodel import Session

    from jobmecloud.oauth import store as oauth

    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    now = datetime.now(timezone.utc)
    _create(client, name="Desktop")
    with Session(client.app.state.engine) as s:
        app = oauth.register_client(s, name="ChatGPT", redirect_uris=["https://chatgpt.com/cb"], now=now)
        code = oauth.issue_code(s, client=app, redirect_uri="https://chatgpt.com/cb", code_challenge=challenge, scope="read", now=now)
        oauth.exchange_code(s, client_id=app.client_id, code=code, redirect_uri="https://chatgpt.com/cb", verifier=verifier, now=now)
    rows = {r["name"]: r for r in client.get("/api/keys").json()}
    assert rows["Desktop"]["via"] == "key" and rows["Desktop"]["app_name"] is None
    sign_in = next(r for n, r in rows.items() if n != "Desktop")
    assert sign_in["via"] == "sign-in" and sign_in["app_name"] == "ChatGPT"
