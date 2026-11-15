from datetime import date

import pytest
from sqlmodel import Session, select

from fakes import FakeProvider, NOW, add_job, deps, get_status, setup_profile
from jobmecloud.agents.jobscout.pipeline import run_jobscout
from jobmecloud.config.settings import load_settings, save_settings
from jobmecloud.db.models import ActivityLog, FollowUp, Job
from jobmecloud.llm.search import FetchResult

TODAY = date(2026, 11, 12)


@pytest.fixture
def c(client):
    client.app.state.today = lambda: TODAY
    return client


def _status(c, jid, **body):
    return c.post(f"/api/jobs/{jid}/status", json=body)


def _logs(engine, jid):
    with Session(engine) as s:
        return list(s.exec(select(ActivityLog).where(ActivityLog.job_id == jid)))


def test_mark_applied_creates_check_in(c, engine):
    jid = add_job(engine)
    r = _status(c, jid, status="Applied", date="2026-11-10")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "Applied" and body["applied_date"] == "2026-11-10"
    assert body["allowed_next"] == ["Interviewing", "Offer", "Rejected", "Withdrawn"]
    with Session(engine) as s:
        fus = list(s.exec(select(FollowUp)))
        assert len(fus) == 1 and fus[0].id == body["follow_up_id"]
        assert fus[0].due_date == date(2026, 11, 17) and fus[0].job_id == jid
    r2 = _status(c, jid, status="Applied")
    assert r2.status_code == 400
    with Session(engine) as s:
        assert len(list(s.exec(select(FollowUp)))) == 1


def test_applied_without_default_days_has_no_follow_up(c, engine, data_dir):
    s = load_settings(data_dir)
    s.followup_default_days = 0
    save_settings(data_dir, s)
    jid = add_job(engine)
    assert _status(c, jid, status="Applied").json()["follow_up_id"] is None


@pytest.mark.parametrize("extra", [{}, {"skip_reason": "  "}, {"skip_reason": "Because"}])
def test_skip_needs_a_listed_reason(c, engine, extra):
    jid = add_job(engine)
    r = _status(c, jid, status="Skipped", **extra)
    assert (r.status_code, r.json()["detail"]) == (400, "Choose why you're skipping this job.")
    assert get_status(engine, jid) == "New"
    assert _logs(engine, jid) == []


def test_skip_with_reason(c, engine):
    jid = add_job(engine)
    r = _status(c, jid, status="Skipped", skip_reason="Pay too low", skip_note="Under 150k")
    assert r.status_code == 200 and r.json()["allowed_next"] == ["Reopen"]
    with Session(engine) as s:
        j = s.get(Job, jid)
        assert (j.skip_reason, j.skip_note) == ("Pay too low", "Under 150k")


def test_full_path(c, engine):
    jid = add_job(engine)
    for status, day in [("Applied", "2026-11-01"), ("Interviewing", "2026-11-05"),
                        ("Offer", "2026-11-08"), ("Accepted", "2026-11-10")]:
        assert _status(c, jid, status=status, date=day).status_code == 200
    with Session(engine) as s:
        j = s.get(Job, jid)
        assert (j.applied_at.date(), j.first_response_at.date(), j.outcome_at.date()) == \
               (date(2026, 11, 1), date(2026, 11, 5), date(2026, 11, 10))
    assert len([x for x in _logs(engine, jid) if x.action == "status_changed"]) == 4


def test_unknown_job_is_404(c):
    r = _status(c, 999, status="Applied")
    assert (r.status_code, r.json()["detail"]) == (404, "No job with that id")
    assert c.post("/api/jobs/999/reopen", json={}).status_code == 404
    assert c.patch("/api/jobs/999", json={"notes": "x"}).status_code == 404


def test_future_date_refused_on_status(c, engine):
    jid = add_job(engine)
    r = _status(c, jid, status="Applied", date="2026-11-30")
    assert (r.status_code, r.json()["detail"]) == (400, "That date is in the future.")
    assert get_status(engine, jid) == "New"
    with Session(engine) as s:
        assert list(s.exec(select(FollowUp))) == []


def test_closed_job_can_be_applied_and_recheck_leaves_it(c, engine, data_dir):
    setup_profile(data_dir)
    jid = add_job(engine, status="Closed", origin="scout", apply_url="https://Mine.example/")
    assert _status(c, jid, status="Applied").status_code == 200
    gone = {"https://Mine.example/": FetchResult("u", 404, "")}
    run_jobscout(data_dir, engine, deps(FakeProvider(replies=["nothing found"]), gone), "manual", now=NOW)
    assert get_status(engine, jid) == "Applied"


def test_reopen(c, engine):
    jid = add_job(engine, status="Skipped", skip_reason="Other")
    r = c.post(f"/api/jobs/{jid}/reopen", json={"note": "changed my mind"})
    assert r.status_code == 200 and r.json()["status"] == "New"
    ready = add_job(engine, status="Withdrawn", docs_folder="x")
    assert c.post(f"/api/jobs/{ready}/reopen").json()["status"] == "Ready"
    assert c.post(f"/api/jobs/{jid}/reopen").status_code == 400


def test_patch(c, engine):
    jid = add_job(engine)
    r = c.patch(f"/api/jobs/{jid}", json={"notes": "Call Jordan", "applied_date": "2026-11-03"})
    assert r.status_code == 200
    assert r.json()["applied_date"] == "2026-11-03" and r.json()["status"] == "New"
    with Session(engine) as s:
        assert s.get(Job, jid).notes == "Call Jordan"
    assert [x.note for x in _logs(engine, jid) if x.action == "edited"] == ["dates, notes"]
    r = c.patch(f"/api/jobs/{jid}", json={"applied_date": None})
    assert r.json()["applied_date"] is None
    r = c.patch(f"/api/jobs/{jid}", json={"outcome_date": "2026-12-01"})
    assert (r.status_code, r.json()["detail"]) == (400, "That date is in the future.")


def test_manual_add_and_duplicates(c, engine):
    r = c.post("/api/jobs", json={"employer": "Contoso Health", "title": "Analyst",
                                  "apply_url": "https://Jobs.Contoso.example/a/1", "notes": "n"})
    assert r.status_code == 201 and r.json()["status"] == "New"
    with Session(engine) as s:
        j = s.get(Job, r.json()["id"])
        assert (j.origin, j.source, j.flags, j.hard_rules, j.notes) == \
               ("manual", "jobs.contoso.example", [], [], "n")
        assert [x.action for x in _logs(engine, j.id)] == ["added"]
    same = c.post("/api/jobs", json={"employer": "Contoso Health Inc", "title": "analyst"})
    assert (same.status_code, same.json()["detail"]) == (409, "That job is already in JobMe.")
    link = c.post("/api/jobs", json={"employer": "Other", "title": "Else",
                                     "apply_url": "https://jobs.contoso.example/a/1/"})
    assert link.status_code == 409


def test_manual_add_validation(c):
    r = c.post("/api/jobs", json={"employer": "  ", "title": "x"})
    assert (r.status_code, r.json()["detail"]) == (400, "Please enter the employer and the job title.")
    r = c.post("/api/jobs", json={"employer": "A", "title": "B", "apply_url": "ftp://x"})
    assert (r.status_code, r.json()["detail"]) == (400, "The link should start with https://")


def test_manual_add_duplicate_ignores_blank_or_missing_location(c, engine):
    add_job(engine, employer="Northwind Labs", title="Data Engineer", location="Austin, TX")
    r = c.post("/api/jobs", json={"employer": "Northwind Labs", "title": "Data  Engineer"})
    assert (r.status_code, r.json()["detail"]) == (409, "That job is already in JobMe.")
    add_job(engine, employer="Contoso Health", title="Analyst", location=None)
    r = c.post("/api/jobs", json={"employer": "Contoso Health", "title": "Analyst", "location": "Remote"})
    assert r.status_code == 409


def test_manual_add_different_locations_allowed_but_same_link_is_not(c, engine):
    add_job(engine, employer="Northwind Labs", title="Data Engineer", location="Austin, TX",
            apply_url="https://jobs.example/1")
    r = c.post("/api/jobs", json={"employer": "Northwind Labs", "title": "Data Engineer",
                                  "location": "Denver, CO"})
    assert r.status_code == 201
    r = c.post("/api/jobs", json={"employer": "Else", "title": "Different",
                                  "apply_url": "https://JOBS.example/1/"})
    assert r.status_code == 409
