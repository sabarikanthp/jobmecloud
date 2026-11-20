"""The tools Claude Desktop can call, and the context each call runs in."""

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


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, input_schema: dict, *, write: bool = False, ai_cost: bool = False):
    def register(fn: Callable[["ToolContext", dict], Any]):
        TOOLS[name] = Tool(name, description, input_schema, fn, write=write, ai_cost=ai_cost)
        return fn
    return register


def untrusted(text: str | None) -> str | None:
    """Mark text that came from a job posting or the outside, so the chat treats it as data, not instructions."""
    if text is None:
        return None
    return f"<untrusted_data>\n{text}\n</untrusted_data>"


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

    def call(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        """Run one of the app's own routes in-process (same checks, same history), as this key."""
        host = self.app.state.first_host
        client = TestClient(self.app, base_url=f"http://{host}", raise_server_exceptions=False)
        with acting_as(f"claude:{self.key.name}"):
            response = client.request(method, path, json=json, params=params)
        if response.status_code >= 400:
            raise ToolError(_detail(response))
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        return response.json()
