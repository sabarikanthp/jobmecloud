import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from jobmecloud.db.models import ApiKey, OAuthCode, OAuthGrant
from jobmecloud.keys import store as keys
from jobmecloud.oauth import store as oauth

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
VERIFIER = "v" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
REDIRECT = "https://chatgpt.com/cb"


def make_client(session, now=NOW, name="ChatGPT"):
    return oauth.register_client(session, name=name, redirect_uris=[REDIRECT], now=now)


def connect(session, scope="read", now=NOW):
    client = make_client(session, now)
    code = oauth.issue_code(session, client=client, redirect_uri=REDIRECT, code_challenge=CHALLENGE, scope=scope, now=now)
    tokens = oauth.exchange_code(session, client_id=client.client_id, code=code, redirect_uri=REDIRECT,
                                 verifier=VERIFIER, now=now)
    return client, code, tokens


@pytest.mark.parametrize("uri", ["http://example.com/cb", "javascript:alert(1)", "https://x.com/" + "a" * 3000, "", "ftp://x.com/cb"])
def test_register_rejects_bad_redirects(session, uri):
    with pytest.raises(oauth.OAuthError) as e:
        oauth.register_client(session, name="x", redirect_uris=[uri], now=NOW)
    assert e.value.code == "invalid_client_metadata"


def test_register_rejects_no_redirects_and_accepts_good_ones(session):
    with pytest.raises(oauth.OAuthError):
        oauth.register_client(session, name="x", redirect_uris=[], now=NOW)
    assert oauth.register_client(session, name="x", redirect_uris=["https://chatgpt.com/cb"], now=NOW).client_id
    assert oauth.register_client(session, name="y", redirect_uris=["http://localhost:8080/cb"], now=NOW).client_id
    assert oauth.register_client(session, name="z", redirect_uris=["http://127.0.0.1:9/cb"], now=NOW).client_id


def test_register_caps_clients_and_prunes_unapproved_after_a_day(session):
    for i in range(oauth.MAX_CLIENTS):
        make_client(session, name=f"c{i}")
    with pytest.raises(oauth.OAuthError) as e:
        make_client(session, name="one too many")
    assert e.value.code == "invalid_client_metadata"
    assert make_client(session, now=NOW + timedelta(hours=25), name="later").client_id


def test_register_truncates_long_names(session):
    assert len(oauth.register_client(session, name="n" * 500, redirect_uris=[REDIRECT], now=NOW).name) == 60


def test_code_exchange_happy_path(session):
    client, _, tokens = connect(session, scope="readwrite")
    assert tokens.access_token.startswith("jmo_")
    assert tokens.expires_in == 3600
    assert tokens.scope == "readwrite"
    key = keys.verify_key(session, tokens.access_token, NOW)
    assert key is not None and key.scope == "readwrite"
    assert "ChatGPT" in key.name
    assert key.expires_at.replace(tzinfo=timezone.utc) == NOW + timedelta(days=30)
    assert oauth.access_valid(session, key, NOW) is True


def test_access_valid_only_within_the_hour(session):
    _, _, tokens = connect(session)
    key = keys.verify_key(session, tokens.access_token, NOW)
    assert oauth.access_valid(session, key, NOW + timedelta(minutes=59)) is True
    assert oauth.access_valid(session, key, NOW + timedelta(minutes=61)) is False


def test_code_is_single_use_and_reuse_revokes_the_key(session):
    client, code, tokens = connect(session)
    with pytest.raises(oauth.OAuthError) as e:
        oauth.exchange_code(session, client_id=client.client_id, code=code, redirect_uri=REDIRECT, verifier=VERIFIER, now=NOW)
    assert e.value.code == "invalid_grant"
    assert keys.verify_key(session, tokens.access_token, NOW) is None
    assert session.exec(select(ApiKey)).one().revoked_at is not None


def test_exchange_rejects_wrong_verifier_redirect_client_and_age(session):
    client = make_client(session)
    other = oauth.register_client(session, name="other", redirect_uris=[REDIRECT], now=NOW)

    def fresh():
        return oauth.issue_code(session, client=client, redirect_uri=REDIRECT, code_challenge=CHALLENGE, scope="read", now=NOW)

    cases = [
        dict(client_id=client.client_id, code=fresh(), redirect_uri=REDIRECT, verifier="w" * 50, now=NOW),
        dict(client_id=client.client_id, code=fresh(), redirect_uri="https://chatgpt.com/other", verifier=VERIFIER, now=NOW),
        dict(client_id=other.client_id, code=fresh(), redirect_uri=REDIRECT, verifier=VERIFIER, now=NOW),
        dict(client_id=client.client_id, code=fresh(), redirect_uri=REDIRECT, verifier=VERIFIER, now=NOW + timedelta(minutes=6)),
        dict(client_id=client.client_id, code="not-a-code", redirect_uri=REDIRECT, verifier=VERIFIER, now=NOW),
    ]
    for kwargs in cases:
        with pytest.raises(oauth.OAuthError) as e:
            oauth.exchange_code(session, **kwargs)
        assert e.value.code == "invalid_grant"
    assert session.exec(select(ApiKey)).first() is None


def test_codes_are_stored_hashed(session):
    _, code, _ = connect(session)
    assert code not in [row.code_hash for row in session.exec(select(OAuthCode))]


def test_refresh_rotates_in_place(session):
    client, _, first = connect(session)
    later = NOW + timedelta(minutes=30)
    second = oauth.refresh(session, client_id=client.client_id, refresh_token=first.refresh_token, now=later)
    assert second.access_token != first.access_token and second.refresh_token != first.refresh_token
    assert keys.verify_key(session, first.access_token, later) is None
    key = keys.verify_key(session, second.access_token, later)
    assert key is not None and session.exec(select(ApiKey)).one().id == key.id
    assert key.expires_at.replace(tzinfo=timezone.utc) == later + timedelta(days=30)
    assert oauth.access_valid(session, key, later) is True
    with pytest.raises(oauth.OAuthError) as e:
        oauth.refresh(session, client_id=client.client_id, refresh_token=first.refresh_token, now=later)
    assert e.value.code == "invalid_grant"
    assert session.exec(select(OAuthGrant)).one().refresh_hash not in (first.refresh_token, second.refresh_token)


def test_refresh_refused_after_revoke_expiry_or_for_another_client(session):
    client, _, tokens = connect(session)
    other = oauth.register_client(session, name="other", redirect_uris=[REDIRECT], now=NOW)
    with pytest.raises(oauth.OAuthError):
        oauth.refresh(session, client_id=other.client_id, refresh_token=tokens.refresh_token, now=NOW)
    with pytest.raises(oauth.OAuthError):
        oauth.refresh(session, client_id=client.client_id, refresh_token=tokens.refresh_token, now=NOW + timedelta(days=31))
    keys.revoke_key(session, session.exec(select(ApiKey)).one().id, NOW)
    with pytest.raises(oauth.OAuthError) as e:
        oauth.refresh(session, client_id=client.client_id, refresh_token=tokens.refresh_token, now=NOW)
    assert e.value.code == "invalid_grant"
