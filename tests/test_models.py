import pytest
from fakes import FakeProvider

from jobmecloud.config.defaults import STEP_NAMES, default_steps
from jobmecloud.config.settings import ProviderConfig, Settings
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.errors import ProviderAuthError
from jobmecloud.llm.steps import StepNotConfiguredError, provider_for_step
from jobmecloud.llm.structured import StructuredOutputError


def test_claude_defaults():
    steps = default_steps(ProviderConfig(id="c", kind="anthropic", label="Claude"), None)
    assert steps["search"].model == "claude-sonnet-5-5" and steps["score"].model == "claude-haiku-5-5"
    assert steps["tailor"].model == "claude-sonnet-5-5" and steps["extract"].model == "claude-haiku-5-5"
    assert steps["liveness"].model == "claude-haiku-5-5"


def test_other_kind_needs_model():
    cfg = ProviderConfig(id="o", kind="openai_compatible", label="L", base_url="http://x/v1")
    assert {s.model for s in default_steps(cfg, "qwen3:8b").values()} == {"qwen3:8b"}
    with pytest.raises(ValueError):
        default_steps(cfg, "")


def test_apply_defaults_route(client):
    client.put("/api/providers/c", json={"id": "c", "kind": "anthropic", "label": "Claude"})
    steps = client.post("/api/steps/defaults", json={"provider_id": "c", "model": None}).json()
    assert set(steps) == set(STEP_NAMES)
    assert client.get("/api/settings").json()["steps"]["search"]["model"] == "claude-sonnet-5-5"


def test_apply_defaults_errors(client):
    r = client.post("/api/steps/defaults", json={"provider_id": "nope", "model": None})
    assert r.status_code == 404 and r.json()["detail"] == "No provider with that id"
    client.put(
        "/api/providers/o",
        json={"id": "o", "kind": "openai_compatible", "label": "L", "base_url": "http://x/v1"},
    )
    r = client.post("/api/steps/defaults", json={"provider_id": "o", "model": ""})
    assert r.status_code == 400 and r.json()["detail"] == "Enter the model name to use."


def test_models_route(client):
    body = client.get("/api/models").json()
    assert [s["id"] for s in body["steps"]] == list(STEP_NAMES)
    assert body["steps"][0]["label"] == "Searching"
    assert "claude-sonnet-5-5" in body["recommended"]["anthropic"]
    assert body["local_note"].startswith("Small local models")


def test_provider_for_step_missing():
    with pytest.raises(StepNotConfiguredError, match="Connect an AI first."):
        provider_for_step(Settings(), "extract", lambda c: FakeProvider())


def test_provider_for_step_found():
    cfg = ProviderConfig(id="c", kind="anthropic", label="Claude")
    settings = Settings(providers=[cfg], steps=default_steps(cfg, None))
    fake = FakeProvider()
    provider, model = provider_for_step(settings, "extract", lambda c: fake)
    assert provider is fake and model == "claude-haiku-5-5"


def test_friendly_message_hides_raw_text():
    assert friendly_message(ProviderAuthError("{'type': 'error'}")) == "The API key was rejected. Check that you copied the whole key."


def test_friendly_message_structured_output():
    assert friendly_message(StructuredOutputError("bad")) == (
        "The AI's answer couldn't be used. Try again, or fill in the form yourself."
    )


def test_edit_keeps_position(client):
    for pid in ["a", "b"]:
        client.put(f"/api/providers/{pid}", json={"id": pid, "kind": "anthropic", "label": pid})
    client.put("/api/providers/a", json={"id": "a", "kind": "anthropic", "label": "A2"})
    assert [p["id"] for p in client.get("/api/providers").json()] == ["a", "b"]


def test_openai_real_sdk_unwraps_error_body():
    import httpx
    import openai

    from jobmecloud.llm.errors import status_message

    resp = httpx.Response(
        400,
        request=httpx.Request("POST", "https://x"),
        json={"error": {"message": "Your credit balance is too low."}},
    )
    client = openai.OpenAI(api_key="k", base_url="http://localhost:1/v1")
    err = client._make_status_error("Error code: 400", body=resp.json(), response=resp)
    assert status_message(err) == "Your credit balance is too low."
