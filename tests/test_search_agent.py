from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from fakes import FakeProvider, tool_reply
from jobmecloud.agents.jobscout.search_agent import (
    MAX_CANDIDATES,
    Candidate,
    build_search_prompt,
    find_candidates,
    make_tools,
    todays_watchlist,
)
from jobmecloud.config.profile import SearchProfile
from jobmecloud.db.models import Job, WatchlistEmployer
from jobmecloud.llm.loop import ToolError
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult, SearchResult

PROFILE = SearchProfile(target_roles=["Data Engineer"], locations=["Springfield"], positioning="Builds pipelines.",
                        excluded_employers=["Fabrikam"], rotation={"mon": "Downtown Springfield"})


def test_prompt_has_profile_rotation_watchlist_and_exclusions():
    wl = [WatchlistEmployer(name="Northwind Labs", priority=1, careers_url="https://northwind.example/careers")]
    system, prompt = build_search_prompt(PROFILE, "mon", wl, max_searches=12)
    text = system + prompt
    for s in ["Data Engineer", "Springfield", "Downtown Springfield", "Northwind Labs",
              "https://northwind.example/careers", "Fabrikam", "12", "check_seen_job", "LinkedIn"]:
        assert s in text
    assert "Downtown Springfield" not in "".join(build_search_prompt(PROFILE, "tue", [], 12))


def test_todays_watchlist():
    e = lambda n, p, d: WatchlistEmployer(name=n, priority=p, rotation_day=d)
    wl = [e("b", 2, None), e("a", 2, "mon"), e("z", 1, "tue"), e("c", 1, "mon")]
    assert [x.name for x in todays_watchlist(wl, "mon")] == ["c", "a", "b"]


def test_record_candidate_validates_dedupes_and_caps(client):
    cands = []
    tools = {t.spec.name: t for t in make_tools(engine=client.app.state.engine, candidates=cands, search=None, max_searches=5)}
    assert set(tools) == {"record_candidate", "check_seen_job"}
    rec = tools["record_candidate"].run
    assert rec({"url": "https://jobs.example/1#top", "employer": "Acme", "title": "Eng"}) == "Recorded. 1 jobs so far."
    assert rec({"url": "https://JOBS.example/1/", "employer": "Acme", "title": "Eng"}) == "Already recorded."
    with pytest.raises(ToolError, match="http"):
        rec({"url": "jobs.example/2", "employer": "Acme", "title": "Eng"})
    with pytest.raises(ToolError, match="Give the url"):
        rec({"url": "https://jobs.example/3", "employer": "", "title": "Eng"})
    for i in range(MAX_CANDIDATES - 1):
        rec({"url": f"https://jobs.example/x{i}", "employer": "A", "title": "T"})
    with pytest.raises(ToolError, match="most jobs allowed"):
        rec({"url": "https://jobs.example/last", "employer": "A", "title": "T"})


def test_check_seen_job(client):
    with Session(client.app.state.engine) as s:
        s.add(Job(employer="Contoso Health, Inc.", title="Data  Engineer", origin="import", status="Applied",
                  first_seen_at=datetime.now(timezone.utc), apply_url="https://contoso.example/j/9"))
        s.commit()
    check = {t.spec.name: t for t in make_tools(engine=client.app.state.engine, candidates=[], search=None, max_searches=1)}["check_seen_job"].run
    assert check({"employer": "contoso health", "title": "data engineer"}) == "Already seen (status: Applied)."
    assert check({"employer": "X", "title": "Y", "url": "https://contoso.example/j/9/"}) == "Already seen (status: Applied)."
    assert check({"employer": "X", "title": "Y"}) == "Not seen before."


def test_search_web_counts_and_stops(client):
    class S:
        def search(self, q, max_results=8): return [SearchResult("T", "https://a.example", "snip")]
    tools = {t.spec.name: t for t in make_tools(engine=client.app.state.engine, candidates=[], search=S(), max_searches=1)}
    assert tools["search_web"].run({"query": "q"}) == "1. T\nhttps://a.example\nsnip"
    with pytest.raises(ToolError, match="Search limit reached"):
        tools["search_web"].run({"query": "q"})


def test_fetch_page_tool(client):
    class S:
        def search(self, q, max_results=8): return []
    def fetch(url):
        return FetchResult(url, 404 if "gone" in url else 200, "x" * 20_000)
    tools = {t.spec.name: t for t in make_tools(engine=client.app.state.engine, candidates=[], search=S(), max_searches=1, fetch=fetch)}
    run = tools["fetch_page"].run
    assert len(run({"url": "https://a.example/ok"})) == 15_000
    for url in ["https://a.example/gone", "https://www.linkedin.com/jobs/1"]:
        with pytest.raises(ToolError, match="Couldn't open that page"):
            run({"url": url})


def test_find_candidates_runs_the_agent(client):
    p = FakeProvider(replies=[tool_reply(("record_candidate", {"url": "https://a.example/1", "employer": "A", "title": "T"})), "Found 1."])
    cands = []
    result = find_candidates(p, "m", profile=PROFILE, day="mon", watchlist=[], engine=client.app.state.engine,
                             costs=CostTracker({}, 0), search=None, max_searches=4, candidates=cands)
    assert cands == [Candidate("https://a.example/1", "A", "T")] and result.stop == "done"
    assert p.calls[0]["builtin_search"] is True and p.calls[0]["max_searches"] == 4


def test_check_seen_job_survives_malformed_saved_url(client):
    with Session(client.app.state.engine) as s:
        s.add(Job(employer="Contoso", title="Analyst", origin="import", status="Applied",
                  first_seen_at=datetime.now(timezone.utc), apply_url="http://[oops/x"))
        s.commit()
    check = {t.spec.name: t for t in make_tools(engine=client.app.state.engine, candidates=[], search=None, max_searches=1)}["check_seen_job"].run
    assert check({"employer": "X", "title": "Y", "url": "https://x.example/1"}) == "Not seen before."
    assert check({"employer": "X", "title": "Y", "url": "http://[OOPS/x"}) == "Already seen (status: Applied)."
