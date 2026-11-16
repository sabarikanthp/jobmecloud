from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from jobmecloud.db.models import InboundEmail, Run
from jobmecloud.inbound import store

NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)  # the same calendar day in nearly every time zone


def test_record_received_returns_an_id_once_and_none_for_the_same_key(engine):
    first = store.record_received(engine, "inbox/abc", "sender@example.com", NOW)
    assert isinstance(first, int)
    assert store.record_received(engine, "inbox/abc", "sender@example.com", NOW) is None
    with Session(engine) as s:
        assert len(s.exec(select(InboundEmail)).all()) == 1


def test_two_keys_are_independent(engine):
    a = store.record_received(engine, "inbox/a", None, NOW)
    b = store.record_received(engine, "inbox/b", None, NOW)
    assert a != b and None not in (a, b)


def test_new_record_starts_as_received_and_can_be_found_by_key(engine):
    store.record_received(engine, "inbox/abc", "sender@example.com", NOW)
    row = store.get_by_key(engine, "inbox/abc")
    assert (row.status, row.sender, row.run_id, row.note) == (store.RECEIVED, "sender@example.com", None, None)
    assert store.get_by_key(engine, "inbox/missing") is None


def test_set_status_updates_status_run_and_note(engine):
    with Session(engine) as s:
        run = Run(trigger="email", started_at=NOW)
        s.add(run)
        s.commit()
        run_id = run.id
    email_id = store.record_received(engine, "inbox/abc", None, NOW)
    store.set_status(engine, email_id, store.STARTED, run_id=run_id)
    row = store.get_by_key(engine, "inbox/abc")
    assert (row.status, row.run_id, row.note) == (store.STARTED, run_id, None)
    store.set_status(engine, email_id, store.FAILED, note="The report could not be read.")
    row = store.get_by_key(engine, "inbox/abc")
    assert (row.status, row.run_id, row.note) == (store.FAILED, run_id, "The report could not be read.")  # run id kept


def test_started_today_counts_only_started_and_done_on_todays_local_date(engine):
    def add(key, status, when):
        i = store.record_received(engine, key, None, when)
        store.set_status(engine, i, status)

    add("inbox/1", store.STARTED, NOW - timedelta(hours=1))
    add("inbox/2", store.DONE, NOW - timedelta(hours=1))
    add("inbox/3", store.REJECTED, NOW - timedelta(hours=1))
    add("inbox/4", store.FAILED, NOW - timedelta(hours=1))
    add("inbox/5", store.WAITING, NOW - timedelta(hours=1))
    add("inbox/6", store.DONE, NOW - timedelta(days=1))
    assert store.started_today(engine, NOW) == 2


def test_claim_succeeds_once_and_a_second_claim_is_refused(engine):
    email_id = store.record_received(engine, "inbox/abc", None, NOW)
    assert store.claim(engine, email_id, (store.RECEIVED,), NOW) is True
    assert store.claim(engine, email_id, (store.RECEIVED,), NOW) is False
    assert store.get_by_key(engine, "inbox/abc").status == store.PROCESSING


def test_a_stale_claim_can_be_taken_over_but_a_fresh_one_cannot(engine):
    email_id = store.record_received(engine, "inbox/abc", None, NOW)
    store.claim(engine, email_id, (store.RECEIVED,), NOW)
    assert store.claim(engine, email_id, (store.RECEIVED,), NOW + timedelta(minutes=1)) is False
    assert store.claim(engine, email_id, (store.RECEIVED,), NOW + timedelta(minutes=20)) is True


def test_claim_only_takes_an_email_in_an_allowed_status(engine):
    email_id = store.record_received(engine, "inbox/abc", None, NOW)
    store.set_status(engine, email_id, store.DONE)
    assert store.claim(engine, email_id, (store.RECEIVED,), NOW) is False
    assert store.claim(engine, email_id, (store.DONE,), NOW) is True


def test_recent_hides_ignored_mail_unless_asked(engine):
    keep = store.record_received(engine, "inbound/a", None, NOW)
    store.set_status(engine, keep, store.DONE)
    junk = store.record_received(engine, "inbound/b", None, NOW + timedelta(minutes=1))
    store.set_status(engine, junk, store.IGNORED)
    assert [r.s3_key for r in store.recent(engine)] == ["inbound/a"]
    assert [r.s3_key for r in store.recent(engine, include_ignored=True)] == ["inbound/b", "inbound/a"]


def test_set_status_can_fill_in_the_sender(engine):
    email_id = store.record_received(engine, "inbox/abc", None, NOW)
    store.set_status(engine, email_id, store.REJECTED, sender="sender@example.com")
    assert store.get_by_key(engine, "inbox/abc").sender == "sender@example.com"
