import pytest
from sqlmodel import Session, select

from fakes import (FakeProvider, NOW, deps, draft_json_for_fixture, extract_json, ready_profile, score_json,
                   setup_profile)
from jobmecloud.agents.jobscout.pipeline import (COST_CAP_COPY, NOT_READ_FLAG, RunSetupError, execute_run, preflight,
                                                 start_run)
from jobmecloud.agents.jobscout.search_agent import Candidate
from jobmecloud.config.settings import Price, load_settings, save_settings
from jobmecloud.db.models import Job, Run, RunJob
from jobmecloud.jobs.runlock import run_lock_held

NORTHWIND = Candidate("https://a.example/1", "Northwind Labs", "Senior Data Engineer",
                      verdict="consider", note="strong AWS fit")


def run_email(data_dir, engine, provider, candidates, *, d=None):
    run_id = start_run(engine, "email", NOW)
    run = execute_run(data_dir, engine, run_id, d or deps(provider), NOW, source=lambda ctx: list(candidates))
    return run


def test_email_candidates_are_read_scored_and_saved_with_origin_email(data_dir, engine):
    setup_profile(data_dir)
    p = FakeProvider(replies=[extract_json(), score_json(90)])
    run = run_email(data_dir, engine, p, [NORTHWIND])
    assert run.trigger == "email" and run.errors == [] and (run.found, run.new, run.matched) == (1, 1, 1)
    assert p.replies == [] and all(not c.get("tools") for c in p.calls)
    with Session(engine) as s:
        job = s.exec(select(Job)).one()
        assert job.origin == "email" and job.match_score == 90


def test_verdict_and_note_are_saved_in_the_job_notes(data_dir, engine):
    setup_profile(data_dir)
    run_email(data_dir, engine, FakeProvider(replies=[extract_json(), score_json(90)]), [NORTHWIND])
    with Session(engine) as s:
        notes = s.exec(select(Job)).one().notes
    assert "consider" in notes and "strong AWS fit" in notes


def test_a_matched_email_job_gets_documents_under_the_existing_application_cap(data_dir, engine):
    ready_profile(data_dir)
    p = FakeProvider(replies=[extract_json(), score_json(95), draft_json_for_fixture(), '{"problems": []}'])
    run = run_email(data_dir, engine, p, [NORTHWIND], d=deps(p, page_counter=lambda d: 1))
    assert (run.matched, run.prepared) == (1, 1) and p.replies == []
    with Session(engine) as s:
        job = s.exec(select(Job)).one()
        assert job.status == "Ready" and job.docs_folder


def test_email_run_never_needs_or_calls_the_search_step(data_dir, engine):
    setup_profile(data_dir)
    s = load_settings(data_dir)
    s.search_backend = "builtin"  # the fake provider has no built-in search, so a search would fail the run
    save_settings(data_dir, s)
    run = run_email(data_dir, engine, FakeProvider(replies=[extract_json(), score_json(90)]), [NORTHWIND])
    assert run.errors == [] and run.found == 1


def test_email_run_skips_the_older_jobs_recheck(data_dir, engine):
    setup_profile(data_dir)
    with Session(engine) as s:
        s.add(Job(employer="Old", title="Analyst", origin="scout", status="New", first_seen_at=NOW,
                  apply_url="https://old.example/1", flags=[], hard_rules=[]))
        s.commit()
    d = deps(FakeProvider())
    fetched = []
    real = d.fetch
    d.fetch = lambda url: (fetched.append(url), real(url))[1]
    run_email(data_dir, engine, FakeProvider(), [], d=d)
    assert fetched == []


def test_empty_candidate_list_finishes_cleanly_with_zero_found_and_releases_the_lock(data_dir, engine):
    setup_profile(data_dir)
    p = FakeProvider()
    run = run_email(data_dir, engine, p, [])
    assert (run.found, run.new, run.errors) == (0, 0, []) and run.finished_at is not None and p.calls == []
    assert not run_lock_held(engine, NOW)


def test_known_url_is_marked_duplicate_not_reimported(data_dir, engine):
    setup_profile(data_dir)
    with Session(engine) as s:
        s.add(Job(employer="Northwind Labs", title="Senior Data Engineer", origin="scout", status="New",
                  first_seen_at=NOW, apply_url="https://a.example/1"))
        s.commit()
    p = FakeProvider()
    run = run_email(data_dir, engine, p, [NORTHWIND])
    assert (run.found, run.new) == (1, 0) and p.calls == []
    with Session(engine) as s:
        assert [rj.outcome for rj in s.exec(select(RunJob))] == ["duplicate"]
        assert len(s.exec(select(Job)).all()) == 1


def test_cost_cap_still_stops_an_email_run_and_saves_remaining_jobs_unread(data_dir, engine):
    setup_profile(data_dir)
    s = load_settings(data_dir)
    s.prices = {"m": Price(input_per_mtok=1000, output_per_mtok=1000)}
    s.caps.max_spend_per_run_usd = 0.001
    save_settings(data_dir, s)
    second = Candidate("https://b.example/2", "Contoso", "Data Lead")
    p = FakeProvider(replies=[extract_json(), score_json(90)])
    run = run_email(data_dir, engine, p, [NORTHWIND, second])
    assert COST_CAP_COPY.format(cap=0.001) in run.errors
    with Session(engine) as s:
        unread = s.exec(select(Job).where(Job.employer == "Contoso")).one()
        assert NOT_READ_FLAG in unread.flags and unread.origin == "email"


def test_preflight_without_search_does_not_need_a_search_service(data_dir):
    setup_profile(data_dir)
    s = load_settings(data_dir)
    s.search_backend = "builtin"
    save_settings(data_dir, s)
    d = deps(FakeProvider())
    with pytest.raises(RunSetupError):
        preflight(data_dir, d)  # a web-search run does need one
    preflight(data_dir, d, needs_search=False)


def test_failed_setup_check_finishes_the_run_and_releases_the_lock(data_dir, engine):
    setup_profile(data_dir)
    run_id = start_run(engine, "email", NOW)

    def source(ctx):
        raise RunSetupError("Add at least one job title.")

    with pytest.raises(RunSetupError):
        execute_run(data_dir, engine, run_id, deps(FakeProvider()), NOW, source=source)
    with Session(engine) as s:
        run = s.get(Run, run_id)
    assert run.errors == ["Add at least one job title."] and run.finished_at is not None
    assert not run_lock_held(engine, NOW)
