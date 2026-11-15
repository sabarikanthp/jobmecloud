import pytest
from fakes import FakeProvider

from jobmecloud.llm.errors import ProviderError
from jobmecloud.llm.structured import StructuredOutputError, complete_json, extract_json

SCHEMA = {"type": "object", "properties": {"score": {"type": "integer"}},
          "required": ["score"], "additionalProperties": False}


def test_native_passes_schema():
    p = FakeProvider(native=True, replies=['{"score": 80}'])
    data, usage = complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)
    assert data == {"score": 80} and p.calls[0]["output_schema"] == SCHEMA
    assert p.calls[0]["messages"] == [{"role": "user", "content": "x"}]
    assert (usage.input_tokens, usage.output_tokens) == (10, 5)


def test_native_failure_does_not_retry():
    p = FakeProvider(native=True, replies=["nope", '{"score": 1}'])
    with pytest.raises(StructuredOutputError):
        complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)
    assert len(p.calls) == 1


def test_native_refusal_raises():
    p = FakeProvider(native=True, replies=['{"score": 1}'])
    orig = p.complete

    def refusing(**kw):
        r = orig(**kw)
        r.stop = "refusal"
        return r

    p.complete = refusing
    with pytest.raises(StructuredOutputError):
        complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)


def test_prompt_mode_strips_fences():
    p = FakeProvider(native=False, replies=['Sure!\n```json\n{"score": 80}\n```'])
    assert complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)[0] == {"score": 80}
    assert "Reply with only JSON matching this schema:" in p.calls[0]["messages"][0]["content"]
    assert p.calls[0]["output_schema"] is None


def test_prompt_mode_text_around_json():
    p = FakeProvider(native=False, replies=['Here you go: {"score": 5} hope it helps'])
    assert complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)[0] == {"score": 5}


def test_prompt_mode_retries_once_and_sums_usage():
    p = FakeProvider(native=False, replies=['{"score": "high"}', '{"score": 70}'])
    data, usage = complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)
    assert data == {"score": 70} and len(p.calls) == 2
    assert (usage.input_tokens, usage.output_tokens) == (20, 10)
    assert "'high' is not of type 'integer'" in p.calls[1]["messages"][0]["content"]


def test_prompt_mode_gives_up():
    p = FakeProvider(native=False, replies=["nope", "still nope"])
    with pytest.raises(StructuredOutputError):
        complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)
    assert len(p.calls) == 2


def test_prompt_mode_refusal_raises_without_retry():
    p = FakeProvider(native=False, replies=["I can't", '{"score": 1}'])
    orig = p.complete

    def refusing(**kw):
        r = orig(**kw)
        r.stop = "refusal"
        return r

    p.complete = refusing
    with pytest.raises(StructuredOutputError):
        complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)
    assert len(p.calls) == 1


def test_fake_provider_raises_queued_exception():
    p = FakeProvider(replies=[ProviderError("boom")])
    with pytest.raises(ProviderError):
        complete_json(p, model="m", system="s", prompt="x", schema=SCHEMA)


def test_extract_json_array():
    assert extract_json("list: [1, 2] done") == [1, 2]


def test_extract_json_prefers_object():
    assert extract_json('Roles: [1] then {"a": [2]}') == {"a": [2]}


def test_prompt_mode_retry_message_is_truncated():
    long_schema = {"type": "object", "properties": {"x": {"enum": ["y" * 2000]}}, "required": ["x"]}
    p = FakeProvider(native=False, replies=['{"x": "z"}', '{"x": "' + "y" * 2000 + '"}'])
    complete_json(p, model="m", system="s", prompt="x", schema=long_schema)
    retry = p.calls[1]["messages"][0]["content"]
    note = retry.split("was not valid: ", 1)[1].split("\nReply again", 1)[0]
    assert len(note) <= 500
