from fakes import NOW, PAGE, FakeProvider, add_job, deps, extract_json, rec, score_json, setup_profile, tool_reply
from sqlmodel import Session, select

from jobmecloud.agents.jobscout.pipeline import run_jobscout
from jobmecloud.db.models import Job, RunJob
from jobmecloud.llm.search import FetchResult

URL = "https://northwind.example/1"


def outcomes(engine):
    with Session(engine) as s:
        return [rj.outcome for rj in s.exec(select(RunJob).order_by(RunJob.id))]


def jobs(engine):
    with Session(engine) as s:
        return list(s.exec(select(Job).order_by(Job.id)))


def test_a_job_you_already_decided_on_is_saved_as_a_duplicate_with_a_link_and_is_not_scored(data_dir, engine):
    setup_profile(data_dir)
    old = add_job(engine, employer="Northwind Labs", title="Senior Data Engineer", requisition_id="R-1",
                  status="Skipped", skip_reason="Not a fit")
    p = FakeProvider(replies=[tool_reply(rec(URL, "Northwind Labs", "Senior Data Engineer")), "done",
                              extract_json()])  # no score reply: scoring would run out of replies and fail
    run = run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert run.errors == [] and p.replies == []
    repeat = jobs(engine)[-1]
    assert (repeat.status, repeat.repost_of_id, repeat.match_score) == ("Duplicate", old, None)
    assert outcomes(engine) == ["repeat"] and run.new == 0


def test_a_repeat_of_a_duplicate_points_at_the_original(data_dir, engine):
    setup_profile(data_dir)
    original = add_job(engine, employer="Northwind Labs", title="Senior Data Engineer", requisition_id="R-1")
    middle = add_job(engine, employer="Northwind Labs", title="Senior Data Engineer", requisition_id="R-2",
                     status="Duplicate", repost_of_id=original)
    p = FakeProvider(replies=[tool_reply(rec(URL, "Northwind Labs", "Senior Data Engineer")), "done", extract_json()])
    run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert jobs(engine)[-1].repost_of_id == original and middle


def test_a_job_with_a_different_title_and_nothing_in_common_is_still_scored_normally(data_dir, engine):
    setup_profile(data_dir)
    add_job(engine, employer="Northwind Labs", title="Chef", requisition_id="R-1")
    p = FakeProvider(replies=[tool_reply(rec(URL, "Northwind Labs", "Senior Data Engineer")), "done",
                              extract_json(), score_json(80)])
    run = run_jobscout(data_dir, engine, deps(p), "manual", now=NOW)
    assert run.errors == [] and p.replies == [] and outcomes(engine) == ["matched"]
    assert jobs(engine)[-1].status == "New"


def test_the_same_posting_text_under_another_company_name_is_flagged_and_still_scored(data_dir, engine):
    setup_profile(data_dir)
    text = "Lead platform teams, own delivery, mentor technical leads, manage budgets and vendors. " * 12
    old = add_job(engine, employer="Staffing Partner (anonymous company)", title="Director, Engineering",
                  status="Skipped", skip_reason="Pay too low", description=text)
    page = {URL: FetchResult(URL, 200, "Director of Software Engineering. " + text)}
    p = FakeProvider(replies=[tool_reply(rec(URL, "Umbrella Press", "Director of Software Engineering")), "done",
                              extract_json(employer="Umbrella Press", title="Director of Software Engineering"),
                              score_json(70)])
    run = run_jobscout(data_dir, engine, deps(p, page), "manual", now=NOW)
    assert run.errors == [] and p.replies == []
    job = jobs(engine)[-1]
    assert job.status == "New" and job.repost_of_id == old and "Possibly seen before" in job.flags
