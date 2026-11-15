from datetime import date, datetime, timezone

import pytest
from sqlmodel import Session

from fakes import add_job
from jobmecloud.db.models import FollowUp, Interview

TODAY = date(2026, 11, 12)  # a Thursday; its week starts Monday 2026-11-09


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _ok(*failed):
    rules = [{"rule": "Pay floor", "passed": True, "note": ""}]
    return rules + [{"rule": r, "passed": False, "note": "no"} for r in failed]


def _fu(job_id, due, status="Open"):
    return FollowUp(job_id=job_id, type="Other", due_date=due, status=status, created_at=_utc(2026, 11, 1))


@pytest.fixture
def c(client):
    client.app.state.today = lambda: TODAY
    return client


def _status(c, jid, **body):
    r = c.post(f"/api/jobs/{jid}/status", json=body)
    assert r.status_code == 200, r.text
    return r


def test_empty_database(c):
    body = c.get("/api/dashboard?weeks=5").json()
    assert body["funnel"] == {"found": 0, "matched": 0, "applied": 0, "interviewing": 0, "offer": 0}
    assert [w["week_start"] for w in body["weekly"]] == [
        "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09"]
    assert all(w["applied"] == 0 for w in body["weekly"])
    assert body["response"] == {"applied": 0, "responded": 0, "rate": None}
    assert body["skip_reasons"] == [] and body["sources"] == []
    assert body["followups"] == {"overdue": [], "this_week": []}


def test_default_is_twelve_weeks(c):
    weekly = c.get("/api/dashboard").json()["weekly"]
    assert len(weekly) == 12 and weekly[-1]["week_start"] == "2026-11-09"


def test_realistic_numbers(c, engine):
    a = add_job(engine, employer="Contoso Health", match_score=90, source="LinkedIn",
                hard_rules=_ok(), status="Applied", applied_at=_utc(2026, 11, 9))  # Monday
    b = add_job(engine, match_score=80, source="LinkedIn", hard_rules=_ok(), status="Ready")
    cc = add_job(engine, match_score=85, source="Indeed", hard_rules=_ok(), status="Ready")
    add_job(engine, match_score=95, source="Indeed", hard_rules=_ok("Location"))  # failed rule
    add_job(engine, match_score=60, source=None, hard_rules=_ok())
    add_job(engine, match_score=78, source=None, hard_rules=_ok(), status="Skipped", skip_reason="Location")
    add_job(engine, match_score=70, status="Skipped", skip_reason="Location")
    add_job(engine, status="Skipped", skip_reason="Not a fit")
    i = add_job(engine, match_score=76, source="LinkedIn", hard_rules=_ok(), status="Applied",
                applied_at=_utc(2026, 10, 19))  # Monday, first week shown
    add_job(engine, match_score=99, source="Indeed", hard_rules={"legacy": True}, status="Accepted",
            applied_at=_utc(2026, 10, 18), first_response_at=_utc(2026, 10, 20))  # Sunday, before range
    # b: Applied on a Sunday -> Interviewing -> Rejected (never an offer)
    _status(c, b, status="Applied", date="2026-11-08")
    _status(c, b, status="Interviewing", date="2026-11-10")
    _status(c, b, status="Rejected", date="2026-11-11")
    # cc: Applied -> Offer
    _status(c, cc, status="Applied", date="2026-10-27")
    _status(c, cc, status="Offer", date="2026-11-05")
    with Session(engine) as s:
        s.add(Interview(job_id=i, stage="Phone screen"))
        s.add(_fu(a, date(2026, 11, 10)))
        s.add(_fu(a, date(2026, 11, 1), "Snoozed"))
        s.add(_fu(a, date(2026, 11, 1), "Done"))
        s.add(_fu(a, date(2026, 11, 12)))
        s.add(_fu(a, date(2026, 11, 18)))
        s.add(_fu(a, date(2026, 11, 19)))
        s.commit()

    body = c.get("/api/dashboard?weeks=4").json()
    assert body["funnel"] == {"found": 10, "matched": 6, "applied": 5, "interviewing": 4, "offer": 2}
    assert body["weekly"] == [
        {"week_start": "2026-10-19", "applied": 1},   # Monday 10-19 counts
        {"week_start": "2026-10-26", "applied": 1},
        {"week_start": "2026-11-02", "applied": 1},   # Sunday 11-08 belongs to the week before
        {"week_start": "2026-11-09", "applied": 1},   # Monday 11-09 starts the current week
    ]
    assert body["response"] == {"applied": 5, "responded": 3, "rate": 0.6}
    assert body["skip_reasons"] == [{"reason": "Location", "count": 2}, {"reason": "Not a fit", "count": 1}]
    assert body["sources"] == [{"source": "LinkedIn", "count": 3}, {"source": "Indeed", "count": 2},
                               {"source": "Unknown", "count": 1}]
    fu = body["followups"]
    # the two automatic check-ins (7 days after applying) are included
    assert [(r["due_date"], r["bucket"]) for r in fu["overdue"]] == [
        ("2026-11-01", "overdue"), ("2026-11-03", "overdue"), ("2026-11-10", "overdue")]
    assert [r["due_date"] for r in fu["this_week"]] == ["2026-11-12", "2026-11-15", "2026-11-18"]
    assert fu["overdue"][0]["employer"] == "Contoso Health"


def test_sources_cap_at_ten(c, engine):
    for n in range(12):
        for _ in range(12 - n):
            add_job(engine, match_score=80, source=f"Board {n:02d}", hard_rules=_ok())
    add_job(engine, match_score=80, source=None, hard_rules=_ok())
    sources = c.get("/api/dashboard").json()["sources"]
    assert len(sources) == 10
    assert sources[0] == {"source": "Board 00", "count": 12}
    assert sources[-1] == {"source": "Board 09", "count": 3}


def test_unknown_counts_when_large_enough(c, engine):
    for _ in range(2):
        add_job(engine, match_score=80, source=None, hard_rules=_ok())
    add_job(engine, match_score=80, source="Indeed", hard_rules=_ok())
    assert c.get("/api/dashboard").json()["sources"] == [
        {"source": "Unknown", "count": 2}, {"source": "Indeed", "count": 1}]


def test_cutoff_comes_from_settings(c, engine):
    add_job(engine, match_score=60, source="Indeed", hard_rules=_ok())
    assert c.get("/api/dashboard").json()["funnel"]["matched"] == 0
    s = c.get("/api/settings").json()
    s["match_cutoff"] = 50
    assert c.put("/api/settings", json=s).status_code == 200
    assert c.get("/api/dashboard").json()["funnel"]["matched"] == 1


@pytest.mark.parametrize("weeks", [3, 60, 0])
def test_weeks_out_of_range(c, weeks):
    assert c.get(f"/api/dashboard?weeks={weeks}").status_code == 422
