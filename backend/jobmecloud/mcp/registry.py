"""The tools Claude Desktop can call, and the context each call runs in."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobmecloud.db.models import ApiKey
from jobmecloud.jobs.actor import acting_as


class ToolError(Exception):
    """A problem to report back to the chat as a tool error (not a server error)."""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[["ToolContext", dict], Any]
    write: bool = False
    ai_cost: bool = False
    wrap: bool = True  # mark outside text in the result as untrusted (off for the owner's own data)


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, input_schema: dict, *, write: bool = False, ai_cost: bool = False,
         wrap: bool = True):
    def register(fn: Callable[["ToolContext", dict], Any]):
        TOOLS[name] = Tool(name, description, input_schema, fn, write=write, ai_cost=ai_cost, wrap=wrap)
        return fn
    return register


_TAG = re.compile(r"<(/?)untrusted_data>", re.IGNORECASE)


def untrusted(text: str | None) -> str | None:
    """Mark text that came from a job posting or the outside, so the chat treats it as data, not instructions.

    Any wrapper tags already inside the text are defused so the text cannot close the wrapper early."""
    if text is None:
        return None
    safe = _TAG.sub(lambda m: f"&lt;{m.group(1)}untrusted_data&gt;", text)
    return "<untrusted_data>\n" + safe + "\n</untrusted_data>"


# Fields whose text comes from a posting, an email, or something typed about someone else.
OUTSIDE_KEYS = frozenset({
    "employer", "title", "location", "apply_url", "source", "description", "notes", "reasons", "gaps", "skip_note",
    "hard_rules", "note", "outcome_note", "name", "role", "link", "stage", "job_title", "contact_name",
    "resume", "cover_letter", "message",
})


def _wrap_leaves(value: Any) -> Any:
    if isinstance(value, str):
        return untrusted(value)
    if isinstance(value, list):
        return [_wrap_leaves(v) for v in value]
    if isinstance(value, dict):
        return {k: _wrap_leaves(v) for k, v in value.items()}
    return value


def mark_untrusted(value: Any) -> Any:
    """A copy of a tool result with every outside-text field wrapped."""
    if isinstance(value, list):
        return [mark_untrusted(v) for v in value]
    if isinstance(value, dict):
        return {k: _wrap_leaves(v) if k in OUTSIDE_KEYS else mark_untrusted(v) for k, v in value.items()}
    return value


_PLAIN_PATH = re.compile(r"/api/[A-Za-z0-9_/-]*")


def _detail(response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):
        detail = "; ".join(str(d.get("msg", d)) for d in detail)
    return str(detail or response.text or f"Request failed ({response.status_code})")


@dataclass
class ToolContext:
    app: FastAPI
    key: ApiKey
    now: datetime
    today: date
    host: str | None = None  # the Host the outer request arrived with (already accepted by the host check)

    def call(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        """Run one of the app's own routes in-process (same checks, same history), as this key."""
        if not _PLAIN_PATH.fullmatch(path):
            raise ToolError("That path is not allowed.")
        host = self.host or self.app.state.first_host
        client = TestClient(self.app, base_url=f"http://{host}", raise_server_exceptions=False)
        with acting_as(f"claude:{self.key.name}"):
            response = client.request(method, path, json=json, params=params)
        if response.status_code >= 400:
            raise ToolError(_detail(response))
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        return response.json()
