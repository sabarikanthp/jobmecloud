import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from jobmecloud.db.models import ActivityLog, ApiKey, Job
from jobmecloud.keys import store
from jobmecloud.mcp import registry
from jobmecloud.api import routes_mcp

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def dummy_tools():
    saved = dict(registry.TOOLS)
    routes_mcp.reset_limits()

    @registry.tool("echo", "Echo text back.", {"type": "object", "properties": {"text": {"type": "string"}}})
    def echo(ctx, args):
        return {"said": args.get("text", "")}

    @registry.tool("boom", "Always fails.", {"type": "object"})
    def boom(ctx, args):
        raise registry.ToolError("that did not work")

    @registry.tool("change", "Change a job's status.", {"type": "object"}, write=True)
    def change(ctx, args):
        return ctx.call("POST", f"/api/jobs/{args['id']}/status", json={"status": "Applied"})

    @registry.tool("think", "Pretend to spend AI money.", {"type": "object"}, write=True, ai_cost=True)
    def think(ctx, args):
        return {"ok": True}

    yield
    registry.TOOLS.clear()
    registry.TOOLS.update(saved)


def make_key(client, scope="read", **kw):
    with Session(client.app.state.engine) as s:
        row, key = store.create_key(s, name=kw.pop("name", "Desktop"), scope=scope, expires_at=kw.pop("expires_at", None),
                                    now=datetime.now(timezone.utc))
        return row.id, key


def rpc(client, key, method, params=None, id=1, headers=None):
    h = {"Authorization": f"Bearer {key}"} if key else {}
    h.update(headers or {})
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if id is not None:
        body["id"] = id
    return client.post("/api/mcp", json=body, headers=h)


def call(client, key, name, args=None):
    r = rpc(client, key, "tools/call", {"name": name, "arguments": args or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def text(result):
    return json.loads(result["content"][0]["text"])


@pytest.mark.parametrize("header", [None, "Bearer", "Bearer jmc_nope", "Basic abc", "Bearer a b"])
def test_missing_or_bad_key_401_empty_detail(client, header):
    h = {"Authorization": header} if header else {}
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=h)
    assert r.status_code == 401
    assert r.content == b""


def test_revoked_and_expired_keys_are_401(client):
    kid, revoked = make_key(client)
    _, expired = make_key(client, expires_at=datetime.now(timezone.utc) - timedelta(days=1), name="old")
    with Session(client.app.state.engine) as s:
        store.revoke_key(s, kid, NOW)
    assert rpc(client, revoked, "ping").status_code == 401
    assert rpc(client, expired, "ping").status_code == 401


def test_scheme_is_case_insensitive(client):
    _, key = make_key(client)
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    headers={"Authorization": f"bearer {key}"})
    assert r.status_code == 200


def test_get_is_405(client):
    assert client.get("/api/mcp").status_code == 405


def test_initialize_returns_server_info_and_tools_capability(client):
    _, key = make_key(client)
    r = rpc(client, key, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "x", "version": "1"}})
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18"
    assert "tools" in res["capabilities"] and res["serverInfo"]["name"] == "JobMe"


def test_initialized_notification_is_202_empty(client):
    _, key = make_key(client)
    r = rpc(client, key, "notifications/initialized", id=None)
    assert r.status_code == 202 and r.text == ""


def test_tools_list_describes_every_tool(client):
    _, key = make_key(client)
    tools = rpc(client, key, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"echo", "boom", "change", "think"} <= names
    assert all("description" in t and "inputSchema" in t for t in tools)


def test_unknown_method_and_tool(client):
    _, key = make_key(client)
    assert rpc(client, key, "nope").json()["error"]["code"] == -32601
    assert rpc(client, key, "tools/call", {"name": "missing"}).json()["error"]["code"] == -32602


def test_echo_tool_result_shape(client):
    _, key = make_key(client)
    res = call(client, key, "echo", {"text": "hi"})
    assert res["isError"] is False and text(res) == {"said": "hi"}


def test_tool_error_becomes_iserror_result_not_http_500(client):
    _, key = make_key(client)
    res = call(client, key, "boom")
    assert res["isError"] is True and "that did not work" in res["content"][0]["text"]


def test_write_tool_with_read_key_is_tool_error_and_not_run(client):
    _, key = make_key(client, "read")
    with Session(client.app.state.engine) as s:
        job = Job(employer="A", title="B", origin="manual", status="New", first_seen_at=NOW)
        s.add(job); s.commit(); jid = job.id
    res = call(client, key, "change", {"id": jid})
    assert res["isError"] is True
    with Session(client.app.state.engine) as s:
        assert s.get(Job, jid).status == "New"


def test_ctx_call_runs_route_in_process_and_acts_as_key_label(client):
    _, key = make_key(client, "readwrite", name="Laptop")
    with Session(client.app.state.engine) as s:
        job = Job(employer="A", title="B", origin="manual", status="New", first_seen_at=NOW)
        s.add(job); s.commit(); jid = job.id
    res = call(client, key, "change", {"id": jid})
    assert res["isError"] is False
    with Session(client.app.state.engine) as s:
        assert s.get(Job, jid).status == "Applied"
        actors = {r.actor for r in s.exec(select(ActivityLog).where(ActivityLog.job_id == jid))}
    assert "claude:Laptop" in actors


def test_ctx_call_failure_becomes_tool_error(client):
    _, key = make_key(client, "readwrite")
    res = call(client, key, "change", {"id": 99999})
    assert res["isError"] is True


def test_ai_cost_tool_blocked_after_daily_limit(client, monkeypatch):
    monkeypatch.setattr(routes_mcp, "AI_DAILY_LIMIT", 2)
    _, key = make_key(client, "readwrite")
    assert call(client, key, "think")["isError"] is False
    assert call(client, key, "think")["isError"] is False
    third = call(client, key, "think")
    assert third["isError"] is True and "limit" in third["content"][0]["text"].lower()


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(routes_mcp, "RATE_PER_MINUTE", 3)
    _, key = make_key(client)
    codes = [rpc(client, key, "ping").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_last_used_updates(client):
    kid, key = make_key(client)
    rpc(client, key, "ping")
    with Session(client.app.state.engine) as s:
        assert s.get(ApiKey, kid).last_used_at is not None


def test_untrusted_wrapper_helper():
    assert registry.untrusted("hello") == "<untrusted_data>\nhello\n</untrusted_data>"
    assert registry.untrusted(None) is None


def test_keys_routes_not_reachable_with_a_key_tool_surface():
    assert not any("key" in n or "setting" in n for n in registry.TOOLS if n not in ("echo", "boom", "change", "think"))
