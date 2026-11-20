"""Shared helpers for the MCP tool tests: make a key, call a tool, read its JSON answer."""

import json
from datetime import datetime, timezone

from sqlmodel import Session

from jobmecloud.keys import store


def make_key(client, scope="readwrite", name="Desktop") -> str:
    with Session(client.app.state.engine) as s:
        _, key = store.create_key(s, name=name, scope=scope, expires_at=None, now=datetime.now(timezone.utc))
    return key


def call_tool(client, key, tool_name, /, **arguments):
    r = client.post("/api/mcp", headers={"Authorization": f"Bearer {key}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool_name, "arguments": arguments}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def ok(result):
    assert result["isError"] is False, result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


def failed(result) -> str:
    assert result["isError"] is True, result["content"][0]["text"]
    return result["content"][0]["text"]


def plain(text):
    """A wrapped outside-text field without its <untrusted_data> wrapper."""
    start, end = "<untrusted_data>" + chr(10), chr(10) + "</untrusted_data>"
    return text[len(start):-len(end)] if isinstance(text, str) and text.startswith(start) else text
