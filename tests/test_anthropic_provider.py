from types import SimpleNamespace

import json

import anthropic
import httpx
import httpx2
import pytest

from jobmecloud.llm.anthropic_provider import AnthropicProvider
from jobmecloud.llm.errors import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnreachableError,
)
from jobmecloud.llm.types import ToolCall, ToolResult, ToolSpec, Usage


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def server_tool_use_block():
    return SimpleNamespace(type="server_tool_use", id="s1", name="web_search", input={"query": "x"})


class FakeClient:
    def __init__(self):
        self.last_kwargs = None
        self.last_endpoint = None
        self._response = self._make("end_turn", [text_block("ok")], (1, 2))
        self._error = None
        self.messages = SimpleNamespace(create=lambda **kw: self._call("messages", kw))
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kw: self._call("beta.messages", kw))
        )

    @staticmethod
    def _make(stop_reason, content, usage):
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=content,
            usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
        )

    def reply(self, stop_reason="end_turn", content=(), usage=(0, 0)):
        self._response = self._make(stop_reason, list(content), usage)

    def raise_(self, exc):
        self._error = exc

    def _call(self, endpoint, kwargs):
        self.last_endpoint = endpoint
        self.last_kwargs = kwargs
        if self._error:
            raise self._error
        return self._response


@pytest.fixture
def fake_client():
    return FakeClient()


def _complete(client, model="claude-haiku-5-5", **kw):
    return AnthropicProvider("p1", "k", client=client).complete(
        model=model, system="s", messages=[], **kw
    )


def test_builtin_search_and_tools_in_request(fake_client):
    p = AnthropicProvider("p1", "k", client=fake_client)
    p.complete(model="claude-haiku-5-5", system="s", messages=[p.user_message("hi")],
               tools=[ToolSpec("check_seen_job", "d", {"type": "object"})],
               builtin_search=True, max_searches=5)
    kw = fake_client.last_kwargs
    types = [t.get("type") for t in kw["tools"]]
    assert "web_search_20260209" in types and "web_fetch_20260209" in types
    assert kw["tools"][0] == {"name": "check_seen_job", "description": "d",
                              "input_schema": {"type": "object"}}
    assert {"type": "web_search_20260209", "name": "web_search", "max_uses": 5,
            "blocked_domains": ["linkedin.com"]} in kw["tools"]
    assert {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5,
            "blocked_domains": ["linkedin.com"]} in kw["tools"]
    assert kw["messages"] == [{"role": "user", "content": "hi"}]
    assert kw["system"] == "s" and kw["model"] == "claude-haiku-5-5" and kw["max_tokens"] == 16000
    assert fake_client.last_endpoint == "messages"          # haiku: no fallbacks
    assert "fallbacks" not in kw and "betas" not in kw


def test_no_tools_omits_tools_and_thinking_and_temperature(fake_client):
    _complete(fake_client)
    kw = fake_client.last_kwargs
    assert "tools" not in kw and "output_config" not in kw
    assert "thinking" not in kw and "temperature" not in kw


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"])
def test_fallback_models_use_beta_fallbacks(fake_client, model):
    _complete(fake_client, model=model)
    assert fake_client.last_endpoint == "beta.messages"
    assert fake_client.last_kwargs["fallbacks"] == "default"
    assert fake_client.last_kwargs["betas"] == ["server-side-fallback-2026-07-01"]


def test_sonnet_uses_fallbacks(fake_client):
    AnthropicProvider("p1", "k", client=fake_client).complete(
        model="claude-sonnet-5-5", system="s", messages=[])
    assert fake_client.last_endpoint == "beta.messages"
    assert fake_client.last_kwargs["fallbacks"] == "default"


def test_schema_goes_to_output_config(fake_client):
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    _complete(fake_client, output_schema=schema)
    cfg = fake_client.last_kwargs["output_config"]
    assert cfg["format"]["type"] == "json_schema"
    assert cfg["format"]["schema"] == schema


def test_response_mapping(fake_client):
    fake_client.reply(stop_reason="tool_use", content=[
        text_block("Looking"), server_tool_use_block(),
        tool_use_block("t1", "check_seen_job", {"employer": "Acme"})],
        usage=(120, 30))
    r = _complete(fake_client)
    assert r.stop == "tool_use" and r.text == "Looking"
    assert r.tool_calls == [ToolCall("t1", "check_seen_job", {"employer": "Acme"})]
    assert r.usage == Usage(120, 30)
    assert r.assistant_message["role"] == "assistant"
    assert r.assistant_message["content"] == fake_client._response.content


def test_text_blocks_are_joined(fake_client):
    fake_client.reply(content=[text_block("a"), server_tool_use_block(), text_block("b")])
    assert _complete(fake_client).text == "ab"


@pytest.mark.parametrize("reason,expected", [
    ("end_turn", "end"), ("stop_sequence", "end"), ("tool_use", "tool_use"),
    ("pause_turn", "pause"), ("max_tokens", "max_tokens"), ("refusal", "refusal"),
])
def test_stop_reason_mapping(fake_client, reason, expected):
    fake_client.reply(stop_reason=reason)
    assert _complete(fake_client).stop == expected


def test_pause_turn_maps_to_pause(fake_client):
    fake_client.reply(stop_reason="pause_turn", content=[server_tool_use_block()])
    r = _complete(fake_client)
    assert r.stop == "pause" and r.tool_calls == [] and r.text == ""


def test_user_message():
    p = AnthropicProvider("p1", "k", client=object())
    assert p.user_message("hi") == {"role": "user", "content": "hi"}


def test_tool_results_single_message():
    msgs = AnthropicProvider("p1", "k", client=object()).tool_results_messages(
        [ToolResult("t1", "ok"), ToolResult("t2", "bad", is_error=True)])
    assert len(msgs) == 1 and msgs[0]["content"][1]["is_error"] is True
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"][0] == {"type": "tool_result", "tool_use_id": "t1",
                                     "content": "ok", "is_error": False}


def test_connection_error_translated(fake_client):
    fake_client.raise_(anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")))
    with pytest.raises(ProviderUnreachableError):
        _complete(fake_client)


def _status_error(cls, status):
    req = httpx.Request("POST", "https://x")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize("cls,status,expected", [
    (anthropic.AuthenticationError, 401, ProviderAuthError),
    (anthropic.NotFoundError, 404, ModelNotFoundError),
    (anthropic.RateLimitError, 429, ProviderRateLimitError),
    (anthropic.InternalServerError, 500, ProviderError),
])
def test_status_errors_translated(fake_client, cls, status, expected):
    fake_client.raise_(_status_error(cls, status))
    with pytest.raises(expected) as ei:
        _complete(fake_client)
    assert type(ei.value) is expected


def test_default_client_is_lazy(monkeypatch):
    built = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: built.append(kw) or FakeClient())
    p = AnthropicProvider("p1", "k")
    assert built == []
    p.complete(model="claude-haiku-5-5", system="s", messages=[])
    assert built == [{"api_key": "k", "timeout": 300, "max_retries": 1}]


@pytest.mark.parametrize("reason", ["something_new", None])
def test_unknown_stop_reason_is_provider_error(fake_client, reason):
    fake_client.reply(stop_reason=reason)
    with pytest.raises(ProviderError, match="Unexpected stop reason"):
        _complete(fake_client)


def test_no_key_raises_auth_error_and_ignores_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    for key in (None, "", "   "):
        p = AnthropicProvider("p1", key)
        with pytest.raises(ProviderAuthError, match="No API key saved"):
            p.complete(model="claude-haiku-5-5", system="s", messages=[])


def test_round_trip_through_real_sdk_serialization():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [
                {"type": "text", "text": "Looking", "citations": None},
                {"type": "tool_use", "id": "toolu_1", "name": "check_seen_job",
                 "input": {"employer": "Acme"}},
            ]})

    client = anthropic.Anthropic(
        api_key="k", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    p = AnthropicProvider("p", "k", client=client)
    tool = ToolSpec("check_seen_job", "d", {"type": "object"})
    msgs = [p.user_message("hi")]
    r = p.complete(model="claude-haiku-5-5", system="s", messages=msgs, tools=[tool])
    msgs += [r.assistant_message, *p.tool_results_messages([ToolResult("toolu_1", "ok")])]
    p.complete(model="claude-haiku-5-5", system="s", messages=msgs, tools=[tool])

    sent = bodies[1]["messages"]
    assert sent[0] == {"role": "user", "content": "hi"}
    assert sent[1]["role"] == "assistant"
    assert [b["type"] for b in sent[1]["content"]] == ["text", "tool_use"]
    assert sent[1]["content"][1]["id"] == "toolu_1"
    assert sent[2]["role"] == "user"
    assert sent[2]["content"][0]["type"] == "tool_result"
    assert sent[2]["content"][0]["tool_use_id"] == "toolu_1"


def test_status_error_uses_body_message(fake_client):
    req = httpx.Request("POST", "https://x")
    err = anthropic.BadRequestError(
        "raw", response=httpx.Response(400, request=req),
        body={"error": {"message": "Your credit balance is too low."}},
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "Your credit balance is too low."


def test_status_error_unwrapped_body_message(fake_client):
    req = httpx.Request("POST", "https://x")
    err = anthropic.BadRequestError(
        "raw", response=httpx.Response(400, request=req),
        body={"message": "Your credit balance is too low."},
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "Your credit balance is too low."


def test_status_error_detail_body(fake_client):
    req = httpx.Request("POST", "https://x")
    err = anthropic.BadRequestError(
        "raw", response=httpx.Response(400, request=req), body={"detail": "Model not loaded"},
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "Model not loaded"


def test_status_error_without_body_never_leaks_repr(fake_client):
    req = httpx.Request("POST", "https://x")
    err = anthropic.InternalServerError(
        "Error code: 500 - {'x': 1}", response=httpx.Response(500, request=req), body=None,
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "HTTP 500" and "{" not in str(ei.value)


def test_client_has_explicit_timeout():
    client = AnthropicProvider("a", "sk-test")._get_client()
    assert client.timeout == 300
    assert issubclass(anthropic.APITimeoutError, anthropic.APIConnectionError)


def fake_response(stop_reason="end_turn", server_tool_use=None):
    usage = SimpleNamespace(input_tokens=1, output_tokens=2)
    if server_tool_use is not None:
        usage.server_tool_use = server_tool_use
    return SimpleNamespace(stop_reason=stop_reason, content=[text_block("ok")], usage=usage)


def test_context_window_stop_is_max_tokens():
    r = AnthropicProvider._to_response(fake_response(stop_reason="model_context_window_exceeded"))
    assert r.stop == "max_tokens"


def test_web_search_count_read_from_usage():
    r = fake_response(stop_reason="end_turn", server_tool_use=SimpleNamespace(web_search_requests=3))
    assert AnthropicProvider._to_response(r).usage.web_searches == 3
    assert AnthropicProvider._to_response(fake_response(stop_reason="end_turn")).usage.web_searches == 0


def test_client_retries_once():
    assert AnthropicProvider("a", "k")._get_client().max_retries == 1
