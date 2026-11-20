from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select

from jobmecloud.db.models import ApiKey
from jobmecloud.keys import store

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def test_create_returns_key_once_and_stores_only_hash(session):
    row, key = store.create_key(session, name="Desktop", scope="read", expires_at=None, now=NOW)
    assert key.startswith("jmc_")
    assert row.prefix == key[:8]
    stored = session.exec(select(ApiKey)).one()
    assert key not in [str(v) for v in stored.model_dump().values()]
    assert stored.key_hash != key


def test_verify_accepts_valid_key(session):
    row, key = store.create_key(session, name="Desktop", scope="readwrite", expires_at=None, now=NOW)
    found = store.verify_key(session, key, NOW)
    assert found is not None and found.id == row.id


def test_verify_rejects_unknown_revoked_and_expired(session):
    _, good = store.create_key(session, name="a", scope="read", expires_at=None, now=NOW)
    revoked, rkey = store.create_key(session, name="b", scope="read", expires_at=None, now=NOW)
    _, ekey = store.create_key(session, name="c", scope="read", expires_at=NOW + timedelta(days=1), now=NOW)
    assert store.revoke_key(session, revoked.id, NOW) is True
    assert store.verify_key(session, "jmc_nope", NOW) is None
    assert store.verify_key(session, rkey, NOW) is None
    assert store.verify_key(session, ekey, NOW + timedelta(days=2)) is None
    assert store.verify_key(session, ekey, NOW + timedelta(hours=1)) is not None
    assert store.verify_key(session, good, NOW) is not None


def test_scope_must_be_read_or_readwrite(session):
    with pytest.raises(ValueError):
        store.create_key(session, name="x", scope="admin", expires_at=None, now=NOW)


def test_spend_ai_call_stops_at_limit_and_resets_next_day(session):
    row, _ = store.create_key(session, name="x", scope="readwrite", expires_at=None, now=NOW)
    day = date(2026, 11, 20)
    assert store.spend_ai_call(session, row, day, 2) is True
    assert store.spend_ai_call(session, row, day, 2) is True
    assert store.spend_ai_call(session, row, day, 2) is False
    assert store.spend_ai_call(session, row, date(2026, 11, 21), 2) is True


def test_touch_sets_last_used(session):
    row, _ = store.create_key(session, name="x", scope="read", expires_at=None, now=NOW)
    store.touch(session, row, NOW)
    assert session.get(ApiKey, row.id).last_used_at is not None


def test_revoke_unknown_is_false(session):
    assert store.revoke_key(session, 999, NOW) is False
