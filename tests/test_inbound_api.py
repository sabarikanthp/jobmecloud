from datetime import datetime, timedelta, timezone

from jobmecloud.inbound import store

NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)


def test_recent_emails_are_listed_newest_first_with_status_and_note(client, engine):
    first = store.record_received(engine, "inbound/a", "sender@example.com", NOW - timedelta(hours=2))
    store.set_status(engine, first, store.DONE)
    second = store.record_received(engine, "inbound/b", "sender@example.com", NOW)
    store.set_status(engine, second, store.REJECTED, note="The sender is not the allowed sender.")
    body = client.get("/api/inbound").json()
    assert [e["status"] for e in body["emails"]] == ["rejected", "done"]
    assert body["emails"][0]["note"] == "The sender is not the allowed sender."
    assert set(body["emails"][0]) == {"received_at", "status", "note", "run_id"}  # never the key or sender


def test_no_emails_gives_an_empty_list(client):
    assert client.get("/api/inbound").json() == {"emails": []}
