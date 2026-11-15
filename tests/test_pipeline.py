import json
import re
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from fakes import (FakeProvider, FakeSearch, NOW, PAGE, deps, draft_json_for_fixture, extract_json, ready_profile, rec,
                   score_json, setup_profile, tool_reply)
from jobmecloud.agents.jobscout.pipeline import RunDeps, RunSetupError, preflight, run_jobscout, start_run
from docx_fixtures import FIXTURE_READING, make_resume_docx
from jobmecloud.applydocs.make_docs import MISSING_FILE_COPY, STALE_MAPPING_COPY
from jobmecloud.resumes.mapping import MappedParagraph, ResumeMapping
from jobmecloud.resumes.store import add_resume, default_entry, file_path
from jobmecloud.config.defaults import default_steps
from jobmecloud.config.profile import SearchProfile, load_search, save_search
from jobmecloud.config.settings import Price, ProviderConfig, load_settings, save_settings
from jobmecloud.db.models import Job, RunJob
from jobmecloud.jobs.runlock import RunInProgressError, run_lock_held
from jobmecloud.llm.errors import ProviderAuthError, ProviderError
from jobmecloud.llm.search import FetchResult

def test_end_to_end_run(data_dir, engine):
    setup_profile(data_dir)
    with Session(engine) as s:
        s.add(Job(employer="Contoso", title="Analyst", origin="import", status="Applied", first_seen_at=NOW,
                  apply_url="https://contoso.example/9")); s.commit()
    p = FakeProvider(replies=[
        tool_reply(rec("https://northwind.example/1", "Northwind Labs", "Senior Data Engineer"),
                   rec("https://fabrikam.example/2", "Fabrikam", "Data Engineer"),
                   rec("https://contoso.example/9", "Contoso", "Analyst"),
                   rec("https://www.linkedin.com/jobs/view/3", "Litware", "Data Engineer")),
        "Found 4.",
        extract_json(), score_json(88),                                  # northwind -> matched
        extract_json(employer="Fabrikam", title="Data Engineer"),        # fabrikam -> excluded by code rule, no score call
    ])
    run = run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert (run.found, run.new, run.excluded, run.matched, run.prepared) == (4, 3, 1, 1, 0)
    assert run.errors == [] and run.finished_at is not None and run.stage is None
    assert not run_lock_held(engine, NOW)
    with Session(engine) as s:
        outcomes = sorted(rj.outcome for rj in s.exec(select(RunJob)))
        assert outcomes == ["duplicate", "excluded", "matched", "new"]
        nw = s.exec(select(Job).where(Job.employer == "Northwind Labs")).one()
        assert (nw.match_score, nw.status, nw.origin, nw.liveness, nw.source) == (88, "New", "scout", "active", "northwind.example")
        assert "Pay unverified" in nw.flags and nw.pay_verified is False
        lit = s.exec(select(Job).where(Job.employer == "Litware")).one()
        assert lit.flags == ["Couldn't read the posting"] and lit.liveness == "unknown" and lit.match_score is None
    assert (data_dir / "logs" / f"run-{run.id}-search.json").exists()
    assert p.replies == []                                               # no unexpected AI calls


def test_provider_failure_mid_run_keeps_found_jobs(data_dir, engine):
    setup_profile(data_dir)
    p = FakeProvider(replies=[tool_reply(rec("https://a.example/1", "A", "Data Engineer"),
                                         rec("https://b.example/2", "B", "Data Engineer")),
                              "done", ProviderError("boom"), extract_json(employer="B", title="Data Engineer"), score_json(50)])
    run = run_jobscout(data_dir, engine, deps(p, {"https://a.example/1": FetchResult("https://a.example/1", 200, PAGE.replace("Senior Data Engineer", "Data Engineer"))}), "manual", now=NOW)
    assert run.errors == ["A - Data Engineer: The provider returned an error: boom"]
    assert run.new == 2 and not run_lock_held(engine, NOW)
    with Session(engine) as s:
        a = s.exec(select(Job).where(Job.employer == "A")).one()
        assert (a.flags, a.liveness, a.status, a.match_score) == (["Not read: the AI step failed"], "unknown", "New", None)
        assert a.apply_url == "https://a.example/1"
        assert sorted(rj.outcome for rj in s.exec(select(RunJob))) == ["new", "new"]


def test_repeated_ai_failure_reported_once_and_jobs_kept(data_dir, engine):
    setup_profile(data_dir)
    p = FakeProvider(replies=[
        tool_reply(rec("https://a.example/1", "A", "Data Engineer"), rec("https://b.example/2", "B", "Data Engineer"),
                   rec("https://c.example/3", "C", "Data Engineer"), rec("https://d.example/4", "D", "Data Engineer")),
        "done",
        ProviderAuthError("x"),                                          # A: extract fails
        extract_json(employer="B", title="Data Engineer"), ProviderAuthError("x"),   # B: score fails, same message
        ProviderError("boom"),                                           # C: a different message
        ProviderAuthError("x"),                                          # D: same as A again
    ])
    run = run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert run.errors == ["A - Data Engineer: The API key was rejected. Check that you copied the whole key.",
                          "C - Data Engineer: The provider returned an error: boom"]
    assert (run.found, run.new, run.matched) == (4, 4, 0) and p.replies == []
    with Session(engine) as s:
        assert all(j.flags == ["Not read: the AI step failed"] for j in s.exec(select(Job)))


def test_non_ai_failure_still_drops_the_job(data_dir, engine):
    setup_profile(data_dir)
    p = FakeProvider(replies=[tool_reply(rec("https://a.example/1", "A", "Data Engineer")), "done"])

    def fetch(url):
        raise RuntimeError("disk full")

    d = deps(p)
    d.fetch = fetch
    run = run_jobscout(data_dir, engine, d, "manual", now=NOW)
    assert run.errors == ["A - Data Engineer: Something went wrong: disk full"] and run.new == 0


def test_repost_duplicate_key_and_unclear_page(data_dir, engine):
    setup_profile(data_dir)
    p = FakeProvider(replies=[
        tool_reply(rec("https://northwind.example/1", "Northwind Labs", "Senior Data Engineer"),
                   rec("https://jobs.example/2", "Northwind Labs", "Senior Data Engineer"),
                   rec("https://board.example/3", "Northwind Labs", "Senior Data Engineer")),
        "done",
        extract_json(requisition_id="R1"), score_json(80),
        extract_json(requisition_id="R2"), json.dumps({"state": "active"}), score_json(60),
        extract_json(requisition_id="R1"),                               # same req as job 1 -> duplicate
    ])
    unclear = {"https://jobs.example/2": FetchResult("https://jobs.example/2", 200, "Requirements and benefits. " * 30)}
    run = run_jobscout(data_dir, engine, deps(p, unclear), "manual", now=NOW)
    assert run.errors == [] and (run.new, run.matched) == (2, 1) and p.replies == []
    with Session(engine) as s:
        first, second = s.exec(select(Job).order_by(Job.id)).all()
        assert second.repost_of_id == first.id and second.flags[0] == "Repost" and second.liveness == "active"
        outcomes = [rj.outcome for rj in s.exec(select(RunJob).order_by(RunJob.id))]
        assert outcomes == ["matched", "new", "duplicate"]


def test_search_failure_still_finishes(data_dir, engine):
    setup_profile(data_dir)
    run = run_jobscout(data_dir, engine, deps(FakeProvider(replies=[ProviderAuthError("x")])), "manual", now=NOW)
    assert run.errors == ["Search: The API key was rejected. Check that you copied the whole key."] and run.found == 0
    assert not run_lock_held(engine, NOW)


def test_cost_cap_saves_rest_unread(data_dir, engine):
    setup_profile(data_dir)
    s = load_settings(data_dir); s.caps.max_spend_per_run_usd = 0.0001; s.prices = {"m": Price(input_per_mtok=1000, output_per_mtok=1000)}
    save_settings(data_dir, s)
    p = FakeProvider(replies=[tool_reply(rec("https://a.example/1", "A", "T"), rec("https://b.example/2", "B", "T")), "done"])
    run = run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert run.errors == ["Stopped early: this run reached its spending limit ($0.00)."]
    with Session(engine) as s:
        assert all(j.flags == ["Not read: spending limit reached"] for j in s.exec(select(Job)))


def test_recheck_closes_old_scout_jobs_only(data_dir, engine):
    setup_profile(data_dir)
    with Session(engine) as s:
        for emp, origin, status in [("Old", "scout", "New"), ("Mine", "scout", "Applied"), ("Imp", "import", "New")]:
            s.add(Job(employer=emp, title="T", origin=origin, status=status, first_seen_at=NOW, apply_url=f"https://{emp}.example/"))
        s.commit()
    gone = {f"https://{e}.example/": FetchResult("u", 404, "") for e in ("Old", "Mine", "Imp")}
    run = run_jobscout(data_dir, engine, deps(FakeProvider(replies=["nothing found"]), gone), "manual", now=NOW)
    with Session(engine) as s:
        assert {j.employer: j.status for j in s.exec(select(Job))} == {"Old": "Closed", "Mine": "Applied", "Imp": "New"}
        assert [rj.outcome for rj in s.exec(select(RunJob).where(RunJob.run_id == run.id))] == ["closed"]


@pytest.mark.parametrize("change,message", [
    (lambda s, p: setattr(s, "steps", {}), "Connect an AI first."),
    (lambda s, p: setattr(p, "target_roles", []), "Add at least one job title in What you're looking for."),
    (lambda s, p: setattr(s, "search_backend", "builtin"), "Choose a search service (Tavily or Brave) in Settings > AI connection."),
])
def test_preflight_messages(data_dir, change, message):
    setup_profile(data_dir)
    s, prof = load_settings(data_dir), load_search(data_dir)
    change(s, prof); save_settings(data_dir, s); save_search(data_dir, prof)
    with pytest.raises(RunSetupError, match=re.escape(message)):
        preflight(data_dir, deps(FakeProvider()))


def test_second_run_refused(data_dir, engine):
    setup_profile(data_dir)
    start_run(engine, "manual", NOW)
    with pytest.raises(RunInProgressError):
        run_jobscout(data_dir, engine, deps(FakeProvider()), "schedule", now=NOW)


def test_malformed_imported_url_does_not_break_run(data_dir, engine):
    setup_profile(data_dir)
    with Session(engine) as s:
        s.add(Job(employer="Contoso", title="Analyst", origin="import", status="Applied", first_seen_at=NOW,
                  apply_url="http://[oops/x")); s.commit()
    p = FakeProvider(replies=[
        tool_reply(("check_seen_job", {"employer": "Northwind Labs", "title": "Senior Data Engineer",
                                       "url": "https://northwind.example/1"}),
                   rec("https://northwind.example/1", "Northwind Labs", "Senior Data Engineer")),
        "done", extract_json(), score_json(88),
    ])
    run = run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert run.errors == [] and (run.found, run.new, run.matched) == (1, 1, 1)
    assert "Not seen before." in json.dumps(p.calls[1]["messages"][-1]["content"])


def test_zero_searches_skips_the_search_step(data_dir, engine):
    setup_profile(data_dir)
    s = load_settings(data_dir); s.caps.max_searches_per_run = 0; save_settings(data_dir, s)
    p = FakeProvider()
    run = run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert (run.found, run.new, run.errors) == (0, 0, []) and p.calls == []
    assert not (data_dir / "logs" / f"run-{run.id}-search.json").exists()


def test_run_prepares_top_matches(data_dir, engine):
    ready_profile(data_dir)
    s = load_settings(data_dir); s.caps.max_applications_per_run = 1; save_settings(data_dir, s)
    p = FakeProvider(replies=[
        tool_reply(rec("https://a.example/1", "Northwind Labs", "Senior Data Engineer"),
                   rec("https://b.example/2", "Contoso Health", "Senior Data Engineer")), "done",
        extract_json(), score_json(95), extract_json(employer="Contoso Health"), score_json(80),
        draft_json_for_fixture(), '{"problems": []}'])
    run = run_jobscout(data_dir, engine, deps(p, page_counter=lambda d: 1), "manual", now=NOW)
    assert (run.matched, run.prepared) == (2, 1) and p.replies == []
    with Session(engine) as s:
        assert sorted(rj.outcome for rj in s.exec(select(RunJob))) == ["matched", "prepared"]
        nw = s.exec(select(Job).where(Job.employer == "Northwind Labs")).one()
        assert nw.status == "Ready" and nw.docs_folder


def _two_matches():
    return [tool_reply(rec("https://a.example/1", "Northwind Labs", "Senior Data Engineer"),
                       rec("https://b.example/2", "Contoso Health", "Senior Data Engineer")), "done",
            extract_json(), score_json(80), extract_json(employer="Contoso Health"), score_json(95)]


def test_run_skips_docs_silently_without_a_default_resume(data_dir, engine):
    setup_profile(data_dir)                                              # no resume in the store
    p = FakeProvider(replies=_two_matches())
    run = run_jobscout(data_dir, engine, deps(p, page_counter=lambda d: 1), "manual", now=NOW)
    assert (run.matched, run.prepared, run.errors) == (2, 0, []) and p.replies == []
    assert len(p.calls) == 6                                             # search x2, extract and score x2; no tailor calls


def test_run_docs_setup_error_reported_once(data_dir, engine):
    setup_profile(data_dir)
    stale = ResumeMapping(paragraphs=[MappedParagraph(index=0, text="Jordan Example", label="contact")])
    add_resume(data_dir, name="Main", filename="cv.docx", data=make_resume_docx(), reading=FIXTURE_READING,
               mapping=stale, make_default=True, now=NOW)
    # Only the first job's draft and self-check run; the stale mapping stops the stage before the second job.
    p = FakeProvider(replies=[*_two_matches(), draft_json_for_fixture(), '{"problems": []}'])
    run = run_jobscout(data_dir, engine, deps(p, page_counter=lambda d: 1), "manual", now=NOW)
    assert (run.matched, run.prepared, run.errors) == (2, 0, [STALE_MAPPING_COPY]) and p.replies == []
    assert len(p.calls) == 8


def test_run_missing_resume_file_reported_once_before_any_ai_step(data_dir, engine):
    ready_profile(data_dir)
    file_path(data_dir, default_entry(data_dir)).unlink()
    p = FakeProvider(replies=_two_matches())
    run = run_jobscout(data_dir, engine, deps(p, page_counter=lambda d: 1), "manual", now=NOW)
    assert (run.matched, run.prepared, run.errors) == (2, 0, [MISSING_FILE_COPY]) and p.replies == []
    assert len(p.calls) == 6                                             # no tailor calls


def test_run_docs_failure_for_one_job_continues(data_dir, engine):
    ready_profile(data_dir)
    p = FakeProvider(replies=[*_two_matches(), ProviderError("boom"), draft_json_for_fixture(), '{"problems": []}'])
    run = run_jobscout(data_dir, engine, deps(p, page_counter=lambda d: 1), "manual", now=NOW)
    assert run.errors == ["Contoso Health - Senior Data Engineer: The provider returned an error: boom"]
    assert run.prepared == 1 and p.replies == []
    with Session(engine) as s:
        contoso = s.exec(select(Job).where(Job.employer == "Contoso Health")).one()
        northwind = s.exec(select(Job).where(Job.employer == "Northwind Labs")).one()
        assert contoso.docs_error == "The provider returned an error: boom" and contoso.status == "New"
        assert northwind.docs_error is None and northwind.status == "Ready"


def test_run_no_docs_when_cap_is_zero(data_dir, engine):
    ready_profile(data_dir)
    s = load_settings(data_dir); s.caps.max_applications_per_run = 0; save_settings(data_dir, s)
    p = FakeProvider(replies=_two_matches())
    run = run_jobscout(data_dir, engine, deps(p, page_counter=lambda d: 1), "manual", now=NOW)
    assert (run.matched, run.prepared, run.errors) == (2, 0, []) and p.replies == []


def test_run_docs_stop_at_cost_cap(data_dir, engine):
    ready_profile(data_dir)
    s = load_settings(data_dir); s.caps.max_spend_per_run_usd = 0.07; s.prices = {"m": Price(input_per_mtok=1000, output_per_mtok=1000)}
    save_settings(data_dir, s)
    p = FakeProvider(replies=_two_matches())                             # 6 calls of $0.015 each pass the cap
    run = run_jobscout(data_dir, engine, deps(p, page_counter=lambda d: 1), "manual", now=NOW)
    assert (run.matched, run.prepared) == (2, 0) and p.replies == []
    assert run.errors == ["Stopped early: this run reached its spending limit ($0.07)."]


def test_every_found_job_logs_found_and_recheck_close_logs_system_change(data_dir, engine):
    from jobmecloud.db.models import ActivityLog
    setup_profile(data_dir)
    with Session(engine) as s:
        s.add(Job(employer="Old", title="T", origin="scout", status="New", first_seen_at=NOW, apply_url="https://Old.example/"))
        s.add(Job(employer="Mine", title="T", origin="scout", status="Applied", first_seen_at=NOW, apply_url="https://Mine.example/"))
        s.commit()
    gone = {f"https://{e}.example/": FetchResult("u", 404, "") for e in ("Old", "Mine")}
    p = FakeProvider(replies=[tool_reply(rec("https://northwind.example/1", "Northwind Labs", "Senior Data Engineer")),
                              "Found 1.", extract_json(), score_json(88)])
    run_jobscout(data_dir, engine, deps(p, gone), "manual", now=NOW)
    with Session(engine) as s:
        rows = s.exec(select(ActivityLog)).all()
        nw = s.exec(select(Job).where(Job.employer == "Northwind Labs")).one()
        found = [r for r in rows if r.action == "found"]
        assert [(r.job_id, r.actor, r.to_value, r.note) for r in found] == [(nw.id, "system", "New", "northwind.example")]
        old = s.exec(select(Job).where(Job.employer == "Old")).one()
        changed = [r for r in rows if r.action == "status_changed"]
        assert [(r.job_id, r.actor, r.from_value, r.to_value) for r in changed] == [(old.id, "system", "New", "Closed")]
        assert s.exec(select(Job).where(Job.employer == "Mine")).one().status == "Applied"
