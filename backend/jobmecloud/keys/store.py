"""API keys for Claude Desktop: create, check, list, revoke. Only a sha256 hash of a key is stored."""

import hashlib
import hmac
import secrets
from datetime import date, datetime, timezone

from sqlmodel import Session, select

from jobmecloud.db.models import ApiKey

SCOPES = ("read", "readwrite")
PREFIX = "jmc_"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    """SQLite hands datetimes back without a zone; they are always UTC here."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def create_key(session: Session, *, name: str, scope: str, expires_at: datetime | None,
               now: datetime) -> tuple[ApiKey, str]:
    if scope not in SCOPES:
        raise ValueError("scope must be read or readwrite")
    key = PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(name=name, prefix=key[:8], key_hash=_hash(key), scope=scope, created_at=now, expires_at=expires_at)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, key


def verify_key(session: Session, presented: str, now: datetime) -> ApiKey | None:
    row = session.exec(select(ApiKey).where(ApiKey.key_hash == _hash(presented))).first()
    if row is None or not hmac.compare_digest(row.key_hash, _hash(presented)):
        return None
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and _utc(row.expires_at) <= _utc(now):
        return None
    return row


def list_keys(session: Session) -> list[ApiKey]:
    return list(session.exec(select(ApiKey).order_by(ApiKey.id)))


def revoke_key(session: Session, key_id: int, now: datetime) -> bool:
    row = session.get(ApiKey, key_id)
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = now
        session.add(row)
        session.commit()
    return True


def touch(session: Session, key: ApiKey, now: datetime) -> None:
    key.last_used_at = now
    session.add(key)
    session.commit()


def spend_ai_call(session: Session, key: ApiKey, today: date, limit: int) -> bool:
    """Count one AI-cost call against today's cap; False (and no count) when the cap is already reached."""
    if key.ai_day != today:
        key.ai_day, key.ai_count = today, 0
    if key.ai_count >= limit:
        return False
    key.ai_count += 1
    session.add(key)
    session.commit()
    return True
