import dataclasses
from datetime import timedelta

from fakes import FakeProvider, NOW, PAGE, add_job, deps, setup_profile
from sqlmodel import Session

from jobmecloud.agents.jobscout import pipeline
from jobmecloud.agents.jobscout.pipeline import NOT_READ_FLAG, run_jobscout
from jobmecloud.db.models import Job
from jobmecloud.llm.search import FetchResult

FAILED = [{"rule": "Pay", "passed": False, "note": "Too low"}]
PASSED = [{"rule": "Pay", "passed": True, "note": ""}]


def _run(data_dir, engine, monkeypatch, pages=None):
    setup_profile(data_dir)
    monkeypatch.setattr(pipeline, "_search", lambda ctx: [])
    fetched: list[str] = []
    base = deps(FakeProvider(), pages or {})

    def fetch(url):
        fetched.append(url)
        return base.fetch(url)

    run_jobscout(data_dir, engine, dataclasses.replace(base, fetch=fetch), "manual", now=NOW)
    return fetched


def _job(engine, n, **kw):
    return add_job(engine, origin="scout", title=f"Role {n}", apply_url=f"https://x.example/{n}", **kw)


def test_recheck_skips_old_excluded_and_unread_jobs(data_dir, engine, monkeypatch):
    _job(engine, 1, first_seen_at=NOW - timedelta(days=31), hard_rules=PASSED)
    _job(engine, 2, first_seen_at=NOW - timedelta(days=2), hard_rules=FAILED)
    _job(engine, 3, first_seen_at=NOW - timedelta(days=2), hard_rules=PASSED, flags=[NOT_READ_FLAG])
    _job(engine, 4, first_seen_at=NOW - timedelta(days=2), hard_rules=PASSED)
    assert _run(data_dir, engine, monkeypatch) == ["https://x.example/4"]


def test_a_failed_recheck_keeps_the_known_liveness(data_dir, engine, monkeypatch):
    jid = _job(engine, 1, first_seen_at=NOW - timedelta(days=2), hard_rules=PASSED, liveness="active")
    pages = {"https://x.example/1": FetchResult("https://x.example/1", 500, "")}
    _run(data_dir, engine, monkeypatch, pages)
    with Session(engine) as s:
        job = s.get(Job, jid)
    assert job.liveness == "active"
    assert job.last_checked_at is not None


def test_a_recheck_with_no_known_liveness_records_unknown(data_dir, engine, monkeypatch):
    jid = _job(engine, 1, first_seen_at=NOW - timedelta(days=2), hard_rules=PASSED)
    pages = {"https://x.example/1": FetchResult("https://x.example/1", 500, "")}
    _run(data_dir, engine, monkeypatch, pages)
    with Session(engine) as s:
        assert s.get(Job, jid).liveness == "unknown"


def test_a_recheck_that_finds_the_page_open_still_updates_liveness(data_dir, engine, monkeypatch):
    jid = _job(engine, 1, first_seen_at=NOW - timedelta(days=2), hard_rules=PASSED, liveness="unknown")
    page = PAGE.replace("Senior Data Engineer", "Role 1")
    _run(data_dir, engine, monkeypatch, {"https://x.example/1": FetchResult("https://x.example/1", 200, page)})
    with Session(engine) as s:
        assert s.get(Job, jid).liveness == "active"
