import json
from datetime import datetime, timezone

from jobmecloud.agents.jobscout.pipeline import RunDeps
from jobmecloud.config.defaults import default_steps
from jobmecloud.config.profile import SearchProfile, save_search
from jobmecloud.config.settings import ProviderConfig, load_settings, save_settings
from jobmecloud.llm.search import FetchResult
from collections.abc import Callable, Sequence
from typing import Any

from jobmecloud.llm.types import LLMResponse, ToolCall, ToolResult, ToolSpec, Usage
from sqlmodel import Session

from docx_fixtures import FIXTURE_LABELS, FIXTURE_READING, make_resume_docx, set_app_pages
from jobmecloud.applydocs.pages import unverified_page_counter
from jobmecloud.config.profile import UserProfile, save_user
from jobmecloud.db.models import Job
from jobmecloud.resumes.docx_text import iter_paragraphs
from jobmecloud.resumes.mapping import MappedParagraph, ResumeMapping
from jobmecloud.resumes.store import add_resume


def tool_reply(*calls: tuple[str, dict], usage: Usage = Usage(10, 5)) -> LLMResponse:
    tool_calls = [ToolCall(f"c{i}", name, args) for i, (name, args) in enumerate(calls, 1)]
    return LLMResponse(
        text="",
        tool_calls=tool_calls,
        stop="tool_use",
        usage=usage,
        assistant_message={"role": "assistant", "content": [{"name": c.name, "id": c.id} for c in tool_calls]},
    )


class FakeProvider:
    id = "fake"
    supports_builtin_search = False

    def __init__(
        self,
        native: bool = True,
        replies: Sequence[str | Exception | LLMResponse | Callable[[dict], str | LLMResponse]] = (),
        raises: Exception | None = None,
    ):
        self.supports_native_schema = native
        self.replies = list(replies)
        self.raises = raises
        self.calls: list[dict] = []

    def complete(self, **kwargs: Any) -> LLMResponse:
        # Copy messages: the agent loop keeps appending to the same list.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if self.raises is not None:
            raise self.raises
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(kwargs)
        if isinstance(reply, LLMResponse):
            return reply
        return LLMResponse(
            text=reply,
            tool_calls=[],
            stop="end",
            usage=Usage(10, 5),
            assistant_message={"role": "assistant", "content": reply},
        )

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_results_messages(self, results: list[ToolResult]) -> list[Any]:
        return [{"role": "user", "content": [r.content for r in results]}]


NOW = datetime(2026, 11, 9, 14, tzinfo=timezone.utc)   # a Monday in every US time zone
PAGE = "Senior Data Engineer at Northwind Labs. " + "Requirements and benefits. " * 30


class FakeSearch:
    def search(self, query, max_results=8):
        return []


def setup_profile(data_dir, cutoff=75):
    s = load_settings(data_dir)
    s.providers = [ProviderConfig(id="fake", kind="openai_compatible", label="Fake")]
    s.steps = default_steps(s.providers[0], "m"); s.search_backend = "tavily"; s.match_cutoff = cutoff
    save_settings(data_dir, s)
    save_search(data_dir, SearchProfile(target_roles=["Data Engineer"], excluded_employers=["Fabrikam"]))


def deps(provider, pages=None, page_counter=unverified_page_counter):
    pages = pages or {}
    return RunDeps(provider_builder=lambda cfg: provider, search_builder=lambda b: FakeSearch(),
                   fetch=lambda url: pages.get(url, FetchResult(url, 200, PAGE)), page_counter=page_counter)


def extract_json(**kw):
    base = {"employer": "Northwind Labs", "title": "Senior Data Engineer", "requisition_id": "", "location": "Springfield",
            "work_mode": "remote", "pay_min": 0, "pay_max": 0, "posted_date": "", "apply_url": ""}
    return json.dumps({**base, **kw})


def score_json(score, failed=False):
    return json.dumps({"score": score, "deal_breakers": [{"rule": "Clearance", "passed": not failed, "note": ""}] if failed else [],
                       "warnings": [], "reasons": "Fits", "gaps": ""})


def rec(url, employer, title):
    return ("record_candidate", {"url": url, "employer": employer, "title": title})


def fixture_mapping(data=None) -> ResumeMapping:
    return ResumeMapping(paragraphs=[
        MappedParagraph(index=p.index, text=p.text, label=FIXTURE_LABELS.get(p.index, "keep"))
        for p in iter_paragraphs(data or make_resume_docx())
    ])


def draft_json_for_fixture() -> str:
    """A Draft for FIXTURE_READING that the code check keeps unchanged."""
    return json.dumps({
        "content": {
            "headline": "Data Platforms | Engineering Leader",
            "summary": "Data engineer with seven years of experience building reliable pipelines for analytics teams.",
            "roles": [
                {"role": 0, "bullets": [{"source": 1, "text": FIXTURE_READING.roles[0].bullets[1]},
                                        {"source": 0, "text": FIXTURE_READING.roles[0].bullets[0]}]},
                {"role": 1, "bullets": [{"source": 0, "text": FIXTURE_READING.roles[1].bullets[0]}]},
            ],
            "skills": ["SQL", "Python"],
        },
        "letter": {
            "greeting": "Dear Hiring Manager,",
            "paragraphs": ["I would like to apply for the Senior Data Engineer role.",
                           "At Northwind Labs I built pipelines that moved 2 TB of data daily."],
            "sign_off": "Sincerely,",
        },
        "changes": ["Put the cost bullet first."],
        "not_applied": [],
        "impact": "",
    })


def ready_profile(data_dir):
    """setup_profile plus a default .docx resume with a mapping, and the user's contact details."""
    setup_profile(data_dir)
    add_resume(data_dir, name="Main", filename="cv.docx", data=set_app_pages(make_resume_docx(), 1),
               reading=FIXTURE_READING, mapping=fixture_mapping(), make_default=True, now=NOW)
    save_user(data_dir, UserProfile(name="Jordan Example", email="jordan@example.com"))


def add_job(engine, **kw) -> int:
    base = {"employer": "Northwind Labs", "title": "Senior Data Engineer", "origin": "manual",
            "first_seen_at": NOW, "status": "New", "description": "Build data pipelines."}
    with Session(engine) as s:
        job = Job(**{**base, **kw})
        s.add(job)
        s.commit()
        return job.id


def set_status(engine, job_id, status):
    with Session(engine) as s:
        job = s.get(Job, job_id)
        job.status = status
        s.add(job)
        s.commit()


def get_status(engine, job_id) -> str:
    with Session(engine) as s:
        return s.get(Job, job_id).status
