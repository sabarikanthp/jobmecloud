from types import SimpleNamespace

import json

import httpx
import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion

from jobmecloud.llm.errors import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnreachableError,
    ProviderWrongAddressError,
)
from jobmecloud.llm.openai_provider import OpenAICompatibleProvider
from jobmecloud.llm.types import ToolCall, ToolResult, ToolSpec, Usage

_DEFAULT_USAGE = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


def completion(choice, usage=_DEFAULT_USAGE):
    data = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, **choice}],
    }
    if usage is not None:
        data["usage"] = usage
    return ChatCompletion.model_validate(data)


class FakeClient:
    def __init__(self):
        self.last_kwargs = None
        self._error = None
        self._response = completion(
            {"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
        )
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._call))

    def reply(self, choice, usage=_DEFAULT_USAGE):
        self._response = completion(choice, usage)

    def raise_(self, exc):
        self._error = exc

    def _call(self, **kwargs):
        self.last_kwargs = kwargs
        if self._error:
            raise self._error
        return self._response


@pytest.fixture
def fake_client():
    return FakeClient()


def make(client, **kw):
    return OpenAICompatibleProvider("p1", "k", "http://localhost:11434/v1", client=client, **kw)


def _complete(client, **kw):
    return make(client).complete(model="m", system="s", messages=[], **kw)


def test_tools_and_system_in_request(fake_client):
    p = make(fake_client)
    p.complete(model="m", system="s", messages=[p.user_message("hi")],
               tools=[ToolSpec("check_seen_job", "d", {"type": "object"})])
    kw = fake_client.last_kwargs
    assert kw["messages"] == [{"role": "system", "content": "s"},
                              {"role": "user", "content": "hi"}]
    assert kw["tools"] == [{"type": "function", "function": {
        "name": "check_seen_job", "description": "d", "parameters": {"type": "object"}}}]
    assert kw["model"] == "m"
    assert "max_tokens" not in kw and "response_format" not in kw


def test_no_tools_omits_tools_key(fake_client):
    _complete(fake_client)
    assert "tools" not in fake_client.last_kwargs


def test_native_schema_uses_response_format(fake_client):
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    _complete(fake_client, output_schema=schema)
    assert fake_client.last_kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": schema, "strict": True},
    }


def test_prompt_mode_does_not_send_response_format(fake_client):
    p = make(fake_client, structured_output="prompt")
    assert p.supports_native_schema is False
    p.complete(model="m", system="s", messages=[], output_schema={"type": "object"})
    assert "response_format" not in fake_client.last_kwargs


def test_capability_flags(fake_client):
    p = make(fake_client)
    assert p.supports_builtin_search is False and p.supports_native_schema is True


def test_tool_call_mapping(fake_client):
    fake_client.reply({"finish_reason": "tool_calls", "message": {"role": "assistant",
        "content": None, "tool_calls": [{"id": "c1", "type": "function",
        "function": {"name": "check_seen_job", "arguments": "{\"employer\": \"Acme\"}"}}]}},
        usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60})
    r = make(fake_client).complete(model="m", system="s", messages=[])
    assert r.stop == "tool_use"
    assert r.text == ""
    assert r.tool_calls == [ToolCall("c1", "check_seen_job", {"employer": "Acme"})]
    assert r.usage == Usage(50, 10)
    assert r.assistant_message == {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "check_seen_job", "arguments": "{\"employer\": \"Acme\"}"}}]}


def test_assistant_message_omits_tool_calls_when_empty_and_drops_extras(fake_client):
    fake_client.reply({"finish_reason": "stop", "message": {
        "role": "assistant", "content": "hello", "refusal": None, "annotations": [],
        "reasoning": "thinking"}})
    assert _complete(fake_client).assistant_message == {"role": "assistant", "content": "hello"}


def test_assistant_message_keeps_tool_call_extra_content(fake_client):
    fake_client.reply({"finish_reason": "tool_calls", "message": {"role": "assistant",
        "content": None, "tool_calls": [{"id": "c1", "type": "function",
        "function": {"name": "f", "arguments": "{}"},
        "extra_content": {"google": {"thought_signature": "sig"}}}]}})
    msg = _complete(fake_client).assistant_message
    assert msg["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig"}}


@pytest.mark.parametrize("reason", ["stop", "length", "function_call", None])
def test_tool_calls_mean_tool_use_whatever_the_finish_reason(fake_client, reason):
    fake_client.reply({"finish_reason": "tool_calls", "message": {"role": "assistant",
        "content": None, "tool_calls": [{"id": "c1", "type": "function",
        "function": {"name": "f", "arguments": "{}"}}]}})
    fake_client._response.choices[0].finish_reason = reason
    assert _complete(fake_client).stop == "tool_use"


@pytest.mark.parametrize("arguments", ["", None])
def test_empty_tool_arguments_become_empty_dict(fake_client, arguments):
    fake_client.reply({"finish_reason": "tool_calls", "message": {"role": "assistant",
        "content": None, "tool_calls": [{"id": "c1", "type": "function",
        "function": {"name": "f", "arguments": "{}"}}]}})
    fake_client._response.choices[0].message.tool_calls[0].function.arguments = arguments
    assert _complete(fake_client).tool_calls == [ToolCall("c1", "f", {})]


def test_empty_choices_is_provider_error(fake_client):
    fake_client._response.choices = []
    with pytest.raises(ProviderError, match="The provider returned no answer."):
        _complete(fake_client)


def test_invalid_tool_arguments_raise_provider_error(fake_client):
    fake_client.reply({"finish_reason": "tool_calls", "message": {"role": "assistant",
        "content": None, "tool_calls": [{"id": "c1", "type": "function",
        "function": {"name": "check_seen_job", "arguments": "{not json"}}]}})
    with pytest.raises(ProviderError, match="check_seen_job"):
        _complete(fake_client)


def test_missing_usage_is_zero(fake_client):
    fake_client.reply({"finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}},
                      usage=None)
    assert make(fake_client).complete(model="m", system="s", messages=[]).usage == Usage(0, 0)


def test_none_usage_values_are_zero(fake_client):
    # The real SDK builds responses without strict validation, so a local server
    # can leave these as None; ChatCompletion.model_validate would reject that.
    fake_client._response.usage.prompt_tokens = None
    fake_client._response.usage.completion_tokens = None
    assert _complete(fake_client).usage == Usage(0, 0)


@pytest.mark.parametrize("reason,expected", [
    ("stop", "end"), ("tool_calls", "tool_use"),
    ("length", "max_tokens"), ("content_filter", "refusal"),
])
def test_stop_reason_mapping(fake_client, reason, expected):
    fake_client.reply({"finish_reason": reason, "message": {"role": "assistant", "content": "x"}})
    assert _complete(fake_client).stop == expected


def test_model_length_maps_to_max_tokens(fake_client):
    # Not in the SDK's strict enum, but some servers send it.
    fake_client._response.choices[0].finish_reason = "model_length"
    assert _complete(fake_client).stop == "max_tokens"


def test_unmapped_stop_reason_means_end(fake_client):
    fake_client.reply({"finish_reason": "function_call",
                       "message": {"role": "assistant", "content": "x"}})
    assert _complete(fake_client).stop == "end"


def test_none_stop_reason_means_end(fake_client):
    fake_client._response.choices[0].finish_reason = None
    assert _complete(fake_client).stop == "end"


def test_user_message():
    assert make(object()).user_message("hi") == {"role": "user", "content": "hi"}


def test_tool_results_one_message_each():
    msgs = make(object()).tool_results_messages(
        [ToolResult("c1", "ok"), ToolResult("c2", "bad", is_error=True)])
    assert msgs == [
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "tool", "tool_call_id": "c2", "content": "ERROR: bad"},
    ]


def test_builtin_search_rejected(fake_client):
    with pytest.raises(ValueError, match="no built-in search"):
        make(fake_client).complete(model="m", system="s", messages=[], builtin_search=True)


def test_connection_error_translated(fake_client):
    fake_client.raise_(openai.APIConnectionError(request=httpx.Request("POST", "https://x")))
    with pytest.raises(ProviderUnreachableError):
        _complete(fake_client)


def _status_error(cls, status):
    req = httpx.Request("POST", "https://x")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize("cls,status,expected", [
    (openai.AuthenticationError, 401, ProviderAuthError),
    (openai.RateLimitError, 429, ProviderRateLimitError),
    (openai.InternalServerError, 500, ProviderError),
])
def test_status_errors_translated(fake_client, cls, status, expected):
    fake_client.raise_(_status_error(cls, status))
    with pytest.raises(expected) as ei:
        _complete(fake_client)
    assert type(ei.value) is expected


def test_default_client_is_lazy(monkeypatch):
    built = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: built.append(kw) or FakeClient())
    p = OpenAICompatibleProvider("p1", None, "http://localhost:1234/v1")
    assert built == []
    p.complete(model="m", system="s", messages=[])
    assert built == [{"api_key": "not-needed", "base_url": "http://localhost:1234/v1", "timeout": 300, "max_retries": 1}]


def _not_found(message, body=None):
    req = httpx.Request("POST", "https://x")
    return openai.NotFoundError(message, response=httpx.Response(404, request=req), body=body)


@pytest.mark.parametrize("error", [
    _not_found("The model `gpt-x` does not exist"),
    _not_found("Error code: 404", body={"error": {"message": "model 'llama9' not found"}}),
])
def test_404_about_a_model_is_model_not_found(fake_client, error):
    fake_client.raise_(error)
    with pytest.raises(ModelNotFoundError):
        _complete(fake_client)


def test_404_not_about_a_model_is_wrong_address(fake_client):
    fake_client.raise_(_not_found("404 page not found"))
    with pytest.raises(ProviderWrongAddressError) as ei:
        _complete(fake_client)
    assert type(ei.value) is ProviderWrongAddressError


def test_round_trip_through_real_sdk_serialization():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx2.Response(200, json={
            "id": "c1", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "refusal": None, "annotations": [],
                "reasoning": "thinking...",
                "tool_calls": [{"id": "call_1", "type": "function", "function": {
                    "name": "check_seen_job", "arguments": "{\"employer\": \"Acme\"}"}}]}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}})

    client = openai.OpenAI(api_key="k", base_url="http://x/v1",
                           http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    p = OpenAICompatibleProvider("o", "k", "http://x/v1", client=client)
    tool = ToolSpec("check_seen_job", "d", {"type": "object"})
    msgs = [p.user_message("hi")]
    r = p.complete(model="m", system="s", messages=msgs, tools=[tool])
    msgs += [r.assistant_message, *p.tool_results_messages([ToolResult("call_1", "ok")])]
    p.complete(model="m", system="s", messages=msgs, tools=[tool])

    assert bodies[1]["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "check_seen_job", "arguments": "{\"employer\": \"Acme\"}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]


def test_status_error_uses_body_message(fake_client):
    req = httpx.Request("POST", "https://x")
    err = openai.BadRequestError(
        "raw", response=httpx.Response(400, request=req),
        body={"error": {"message": "Your credit balance is too low."}},
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "Your credit balance is too low."


def test_status_error_unwrapped_body_message(fake_client):
    req = httpx.Request("POST", "https://x")
    err = openai.BadRequestError(
        "raw", response=httpx.Response(400, request=req),
        body={"message": "Your credit balance is too low."},
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "Your credit balance is too low."


def test_status_error_detail_body(fake_client):
    req = httpx.Request("POST", "https://x")
    err = openai.BadRequestError(
        "raw", response=httpx.Response(400, request=req), body={"detail": "Model not loaded"},
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "Model not loaded"


def test_status_error_without_body_never_leaks_repr(fake_client):
    req = httpx.Request("POST", "https://x")
    err = openai.InternalServerError(
        "Error code: 500 - {'x': 1}", response=httpx.Response(500, request=req), body=None,
    )
    fake_client.raise_(err)
    with pytest.raises(ProviderError) as ei:
        _complete(fake_client)
    assert str(ei.value) == "HTTP 500" and "{" not in str(ei.value)


def test_client_has_explicit_timeout():
    client = OpenAICompatibleProvider("o", "sk-test", None)._get_client()
    assert client.timeout == 300
    assert issubclass(openai.APITimeoutError, openai.APIConnectionError)


def test_client_retries_once():
    from jobmecloud.llm.openai_provider import OpenAICompatibleProvider as P

    assert P("o", "k", "http://localhost:1/v1")._get_client().max_retries == 1
