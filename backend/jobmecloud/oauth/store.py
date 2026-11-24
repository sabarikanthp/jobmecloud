"""OAuth sign-in for connectors (ChatGPT, Claude): registered apps, one-time codes and token swaps.

Each approved connection is one ApiKey row (so scope, limits, history and Revoke are the ones keys already have)
plus an OAuthGrant row with the 1-hour access expiry and the rotating refresh token. Only hashes are stored.
"""

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlmodel import Session, select

from jobmecloud.db.models import ApiKey, OAuthClient, OAuthCode, OAuthGrant
from jobmecloud.keys.store import as_utc, hash_token

OAUTH_PREFIX = "jmo_"
MAX_CLIENTS = 50
UNAPPROVED_CLIENT_LIFE = timedelta(hours=24)
CODE_LIFE = timedelta(minutes=5)
ACCESS_LIFE = timedelta(hours=1)
CONNECTION_LIFE = timedelta(days=30)  # the refresh token and the connection's ApiKey both last this long
MAX_URI_CHARS = 2000
MAX_REDIRECT_URIS = 10
LOCAL_HOSTS = ("localhost", "127.0.0.1")


class OAuthError(Exception):
    """An OAuth failure; `code` is the standard error name the client sees."""

    def __init__(self, code: str, description: str = "") -> None:
        super().__init__(f"{code}: {description}")
        self.code, self.description = code, description


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str


def _valid_redirect(uri: object) -> bool:
    if not isinstance(uri, str) or not uri or len(uri) > MAX_URI_CHARS or "\x00" in uri:
        return False
    try:
        parts = urlparse(uri)
        host = parts.hostname
    except ValueError:
        return False
    if not host or parts.fragment:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and host in LOCAL_HOSTS)


def _prune(session: Session, now: datetime) -> None:
    """Drop spent-by-time codes and apps that never got approved within a day."""
    for code in session.exec(select(OAuthCode).where(OAuthCode.expires_at <= now)):
        session.delete(code)
    approved = {g.client_id for g in session.exec(select(OAuthGrant))}
    for client in session.exec(select(OAuthClient)):
        if client.client_id not in approved and as_utc(client.created_at) <= now - UNAPPROVED_CLIENT_LIFE:
            session.delete(client)
    session.flush()


def _live_count(session: Session, now: datetime) -> int:
    """Apps that count against the cap: those with a working connection, and those still waiting for approval.
    A connection that was revoked or has run out is over and does not count, so the cap never locks the owner out."""
    keys_by_client: dict[str, list[int]] = {}
    for grant in session.exec(select(OAuthGrant)):
        keys_by_client.setdefault(grant.client_id, []).append(grant.api_key_id)
    keys = {k.id: k for k in session.exec(select(ApiKey))}

    def working(key_id: int) -> bool:
        key = keys.get(key_id)
        return key is not None and key.revoked_at is None and (key.expires_at is None or as_utc(key.expires_at) > now)

    live = 0
    for client in session.exec(select(OAuthClient)):
        ids = keys_by_client.get(client.client_id)
        if ids is None or any(working(i) for i in ids):
            live += 1
    return live


def register_client(session: Session, *, name: str, redirect_uris: list[str], now: datetime) -> OAuthClient:
    if (not isinstance(redirect_uris, list) or not redirect_uris or len(redirect_uris) > MAX_REDIRECT_URIS
            or not all(_valid_redirect(u) for u in redirect_uris)):
        raise OAuthError("invalid_client_metadata", "redirect_uris must be up to 10 https addresses (http only for localhost).")
    if "\x00" in str(name or ""):
        raise OAuthError("invalid_client_metadata", "client_name is not valid.")
    _prune(session, now)
    if _live_count(session, now) >= MAX_CLIENTS:
        raise OAuthError("invalid_client_metadata", "Too many apps are waiting for approval. Try again later.")
    label = (str(name or "").strip() or "Connected app")[:60]
    client = OAuthClient(client_id="jmc-" + secrets.token_urlsafe(16), name=label,
                         redirect_uris=list(redirect_uris), created_at=now)
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


def get_client(session: Session, client_id: str) -> OAuthClient | None:
    if "\x00" in client_id:  # the database cannot hold a NUL byte; no client id has one
        return None
    return session.exec(select(OAuthClient).where(OAuthClient.client_id == client_id)).first()


def check_redirect(client: OAuthClient, redirect_uri: str) -> bool:
    return redirect_uri in client.redirect_uris


def issue_code(session: Session, *, client: OAuthClient, redirect_uri: str, code_challenge: str, scope: str,
               now: datetime) -> str:
    code = secrets.token_urlsafe(32)
    session.add(OAuthCode(code_hash=hash_token(code), client_id=client.client_id, redirect_uri=redirect_uri,
                          code_challenge=code_challenge, scope=scope, expires_at=now + CODE_LIFE))
    session.commit()
    return code


def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge)


def _new_tokens() -> tuple[str, str]:
    return OAUTH_PREFIX + secrets.token_urlsafe(32), secrets.token_urlsafe(32)


def exchange_code(session: Session, *, client_id: str, code: str, redirect_uri: str, verifier: str,
                  now: datetime) -> Tokens:
    _prune(session, now)
    row = session.exec(select(OAuthCode).where(OAuthCode.code_hash == hash_token(code))).first()
    if row is None:
        raise OAuthError("invalid_grant", "That code is not valid.")
    if row.used_at is not None:
        # A used code coming back means it leaked: end the connection it created.
        key = session.get(ApiKey, row.api_key_id) if row.api_key_id else None
        if key is not None and key.revoked_at is None:
            key.revoked_at = now
            session.add(key)
            session.commit()
        raise OAuthError("invalid_grant", "That code was already used.")
    row.used_at = now  # spent on any attempt, so a code cannot be guessed at
    session.add(row)
    if (row.client_id != client_id or row.redirect_uri != redirect_uri or as_utc(row.expires_at) <= now
            or not _pkce_ok(verifier or "", row.code_challenge)):
        session.commit()
        raise OAuthError("invalid_grant", "That code is not valid.")
    client = get_client(session, client_id)
    app_name = client.name if client else "App"
    access, refresh = _new_tokens()
    key = ApiKey(name=f"{app_name} (sign-in)"[:60], prefix=access[:8], key_hash=hash_token(access),
                 scope=row.scope, created_at=now, expires_at=now + CONNECTION_LIFE)
    session.add(key)
    session.flush()
    row.api_key_id = key.id
    session.add(OAuthGrant(api_key_id=key.id, client_id=client_id, access_expires_at=now + ACCESS_LIFE,
                           refresh_hash=hash_token(refresh), refresh_expires_at=now + CONNECTION_LIFE))
    session.commit()
    return Tokens(access, refresh, int(ACCESS_LIFE.total_seconds()), row.scope)


def refresh(session: Session, *, client_id: str, refresh_token: str, now: datetime) -> Tokens:
    grant = session.exec(select(OAuthGrant).where(OAuthGrant.refresh_hash == hash_token(refresh_token or ""))).first()
    key = session.get(ApiKey, grant.api_key_id) if grant else None
    if (grant is None or key is None or grant.client_id != client_id or key.revoked_at is not None
            or as_utc(grant.refresh_expires_at) <= now):
        raise OAuthError("invalid_grant", "That refresh token is not valid.")
    access, new_refresh = _new_tokens()
    key.key_hash, key.prefix, key.expires_at = hash_token(access), access[:8], now + CONNECTION_LIFE
    grant.access_expires_at = now + ACCESS_LIFE
    grant.refresh_hash, grant.refresh_expires_at = hash_token(new_refresh), now + CONNECTION_LIFE
    session.add(key)
    session.add(grant)
    session.commit()
    return Tokens(access, new_refresh, int(ACCESS_LIFE.total_seconds()), key.scope)


def access_valid(session: Session, key: ApiKey, now: datetime) -> bool:
    grant = session.exec(select(OAuthGrant).where(OAuthGrant.api_key_id == key.id)).first()
    return grant is not None and as_utc(grant.access_expires_at) > now


def site_url() -> str:
    """The public address of the site: the OAuth issuer. Set at deploy time, never read from request headers."""
    url = os.environ.get("JOBMECLOUD_SITE_URL", "").strip().rstrip("/")
    if not url:
        raise OAuthError("invalid_request", "Sign-in for connectors needs your own site address (site_domain) at deploy time.")
    return url


def www_authenticate(*, invalid_token: bool) -> str:
    """The WWW-Authenticate value that tells a connector where to find the sign-in metadata."""
    parts = []
    if invalid_token:
        parts.append('error="invalid_token"')
    parts.append(f'resource_metadata="{site_url()}/.well-known/oauth-protected-resource/api/mcp"')
    return "Bearer " + ", ".join(parts)
