"""JobScout step 1: an agent that searches for job postings and records candidates."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from jobmecloud.config.profile import SearchProfile
from jobmecloud.agents.jobscout.liveness import is_blocked_host
from jobmecloud.config.settings import Day
from jobmecloud.db.models import Job, WatchlistEmployer
from jobmecloud.jobs.dedup import normalize_employer, normalize_url
from jobmecloud.llm.loop import AgentResult, Tool, ToolError, run_agent
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult, SearchBackend, SearchError, fetch_page
from jobmecloud.llm.types import Provider, ToolSpec

MAX_CANDIDATES = 40
WATCHLIST_PER_RUN = 15
SEARCH_RESULT_COUNT = 8
FETCH_CHARS = 15_000
CANDIDATE_LIMIT_COPY = "You have recorded the most jobs allowed for one run. Stop searching and finish."
SEARCH_LIMIT_COPY = "Search limit reached. Record what you have found and finish."


@dataclass
class Candidate:
    url: str
    employer: str
    title: str


def todays_watchlist(employers: list[WatchlistEmployer], day: Day) -> list[WatchlistEmployer]:
    due = [e for e in employers if e.rotation_day in (day, None)]
    due.sort(key=lambda e: (e.priority, e.name.lower()))
    return due[:WATCHLIST_PER_RUN]


def build_search_prompt(
    profile: SearchProfile, day: Day, watchlist: list[WatchlistEmployer], max_searches: int
) -> tuple[str, str]:
    system = (
        "You are JobScout, a job-search assistant. Find current job postings that fit the "
        "candidate and save each one with record_candidate.\n"
        "- Prefer the employer's official posting (its own careers site or applicant system) "
        "over job-board copies.\n"
        "- Call check_seen_job before record_candidate, and skip jobs already seen.\n"
        "- Do not open LinkedIn pages. If a job is only on LinkedIn, look for the same job on "
        "the employer's site.\n"
        "- Finish with a one-line summary."
    )
    lines = [
        "Target roles: " + ", ".join(profile.target_roles),
        "Locations: " + ", ".join(profile.locations),
        "Allowed work modes: " + ", ".join(profile.work_modes),
        f"Positioning: {profile.positioning}",
    ]
    area = profile.rotation.get(day)
    if area:
        lines.append(f"Today's rotation area: {area}")
    if watchlist:
        lines.append("Check these employers today:")
        for e in watchlist:
            lines.append(f"- {e.name}" + (f" ({e.careers_url})" if e.careers_url else ""))
    if profile.excluded_employers:
        lines.append("Do not record jobs at: " + ", ".join(profile.excluded_employers))
    lines.append(f"You may run at most {max_searches} searches.")
    return system, "\n".join(lines)


def _title_key(title: str) -> str:
    return " ".join(title.lower().split())


def _object_schema(props: dict[str, str], required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": d} for k, d in props.items()},
        "required": required,
    }


def make_tools(
    *,
    engine: Engine,
    candidates: list[Candidate],
    search: SearchBackend | None,
    max_searches: int,
    fetch: Callable[[str], FetchResult] = fetch_page,
) -> list[Tool]:
    def record(args: dict) -> str:
        url, employer, title = (str(args.get(k) or "").strip() for k in ("url", "employer", "title"))
        if not (url and employer and title):
            raise ToolError("Give the url, employer and title.")
        if not url.lower().startswith(("http://", "https://")):
            raise ToolError("The url must start with http:// or https://")
        key = normalize_url(url)
        if any(normalize_url(c.url) == key for c in candidates):
            return "Already recorded."
        if len(candidates) >= MAX_CANDIDATES:
            raise ToolError(CANDIDATE_LIMIT_COPY)
        candidates.append(Candidate(url, employer, title))
        return f"Recorded. {len(candidates)} jobs so far."

    def check_seen(args: dict) -> str:
        emp = normalize_employer(str(args.get("employer") or ""))
        title = _title_key(str(args.get("title") or ""))
        url = str(args.get("url") or "").strip()
        url_key = normalize_url(url) if url else None
        with Session(engine) as session:
            for job in session.exec(select(Job)).all():
                same_url = bool(url_key and job.apply_url and normalize_url(job.apply_url) == url_key)
                same_job = normalize_employer(job.employer) == emp and _title_key(job.title) == title
                if same_url or same_job:
                    return f"Already seen (status: {job.status})."
        return "Not seen before."

    tools = [
        Tool(
            ToolSpec(
                "record_candidate",
                "Save a job posting you found. Use the employer's own careers page or applicant system when you can.",
                _object_schema(
                    {"url": "Link to the posting", "employer": "Employer name", "title": "Job title"},
                    ["url", "employer", "title"],
                ),
            ),
            record,
        ),
        Tool(
            ToolSpec(
                "check_seen_job",
                "Check whether JobMe already knows this job before you record it.",
                _object_schema(
                    {"employer": "Employer name", "title": "Job title", "url": "Link to the posting (optional)"},
                    ["employer", "title"],
                ),
            ),
            check_seen,
        ),
    ]
    if search is None:
        return tools

    used = 0

    def search_web(args: dict) -> str:
        nonlocal used
        if used >= max_searches:
            raise ToolError(SEARCH_LIMIT_COPY)
        used += 1
        try:
            results = search.search(str(args.get("query") or ""), SEARCH_RESULT_COUNT)
        except SearchError as e:
            raise ToolError(str(e)) from e
        if not results:
            return "No results."
        return "\n\n".join(f"{i}. {r.title}\n{r.url}\n{r.snippet}" for i, r in enumerate(results, 1))

    def fetch_tool(args: dict) -> str:
        url = str(args.get("url") or "")
        if is_blocked_host(url):
            raise ToolError("Couldn't open that page (status 0).")
        result = fetch(url)
        if result.status == 0 or result.status >= 400:
            raise ToolError(f"Couldn't open that page (status {result.status}).")
        return result.text[:FETCH_CHARS]

    tools.append(
        Tool(
            ToolSpec("search_web", "Search the web. Returns titles, links and snippets.",
                     _object_schema({"query": "What to search for"}, ["query"])),
            search_web,
        )
    )
    tools.append(
        Tool(
            ToolSpec("fetch_page", "Open a web page and read its text.",
                     _object_schema({"url": "Page address"}, ["url"])),
            fetch_tool,
        )
    )
    return tools


def find_candidates(
    provider: Provider,
    model: str,
    *,
    profile: SearchProfile,
    day: Day,
    watchlist: list[WatchlistEmployer],
    engine: Engine,
    costs: CostTracker,
    search: SearchBackend | None,
    max_searches: int,
    candidates: list[Candidate],
    fetch: Callable[[str], FetchResult] = fetch_page,
) -> AgentResult:
    system, prompt = build_search_prompt(profile, day, watchlist, max_searches)
    tools = make_tools(engine=engine, candidates=candidates, search=search, max_searches=max_searches, fetch=fetch)
    builtin = search is None
    return run_agent(
        provider,
        model=model,
        system=system,
        prompt=prompt,
        tools=tools,
        costs=costs,
        builtin_search=builtin,
        max_searches=max_searches if builtin else 0,
    )
