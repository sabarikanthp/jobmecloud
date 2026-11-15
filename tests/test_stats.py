from datetime import date, datetime, timezone

from fakes import add_job
from jobmecloud.db.models import ActivityLog
from jobmecloud.jobs import stats

TODAY = date(2026, 11, 12)


def test_matched_treats_odd_hard_rules_as_no_failures(session, engine):
    for rules in (None, [], "oops", ["x"], {"a": 1}, [{"rule": "r", "passed": True}]):
        add_job(engine, match_score=80, hard_rules=rules)
    add_job(engine, match_score=80, hard_rules=[{"rule": "r", "passed": False, "note": ""}])
    assert stats.matched(session, TODAY, 75) == 6


def test_matched_boundary_is_inclusive(session, engine):
    add_job(engine, match_score=75, hard_rules=[])
    add_job(engine, match_score=74, hard_rules=[])
    assert stats.matched(session, TODAY, 75) == 1


def test_offer_uses_the_log_and_interviewing_does_not_count_it(session, engine):
    jid = add_job(engine, status="Rejected")
    session.add(ActivityLog(entity_type="job", entity_id=jid, job_id=jid, action="status_changed",
                            from_value="Applied", to_value="Offer",
                            at=datetime(2026, 11, 1, tzinfo=timezone.utc), actor="user"))
    session.commit()
    assert stats.offer(session, TODAY) == 1
    assert stats.interviewing(session, TODAY) == 0


def test_weekly_is_zero_filled_oldest_first(session, engine):
    rows = stats.weekly(session, TODAY, 4)
    assert [r["week_start"] for r in rows] == ["2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09"]
    assert [r["applied"] for r in rows] == [0, 0, 0, 0]


def test_response_rate(session, engine):
    add_job(engine, applied_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
            first_response_at=datetime(2026, 11, 3, tzinfo=timezone.utc))
    add_job(engine, applied_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert stats.response(session, TODAY) == {"applied": 2, "responded": 1, "rate": 0.5}
