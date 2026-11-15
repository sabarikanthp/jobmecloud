import pytest
from fakes import FakeProvider

from jobmecloud.config.settings import ProviderConfig
from jobmecloud.llm.anthropic_provider import AnthropicProvider
from jobmecloud.llm.connection import ConnectionResult, check_provider, check_search
from jobmecloud.llm.errors import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnreachableError,
    ProviderWrongAddressError,
)
from jobmecloud.llm.factory import build_provider, build_search
from jobmecloud.llm.openai_provider import OpenAICompatibleProvider
from jobmecloud.llm.search import BraveSearch, SearchError, SearchResult, TavilySearch
from jobmecloud.secrets import set_secret


class FakeSearch:
    def __init__(self, raises=None):
        self.raises = raises
        self.queries = []

    def search(self, query, max_results=8):
        self.queries.append((query, max_results))
        if self.raises is not None:
            raise self.raises
        return [SearchResult("t", "https://example.com", "s")]


@pytest.mark.parametrize("exc,expected", [
    (None, "Connected. The model replied."),
    (ProviderAuthError("x"), "The API key was rejected. Check that you copied the whole key."),
    (ProviderUnreachableError("x"), "Couldn't reach the provider."),
    (ModelNotFoundError("x"), "Connected, but the model name wasn't found. Check the spelling."),
    (ProviderRateLimitError("x"), "Connected, but the provider says you're over your limit."),
    (ProviderWrongAddressError("x"),
     "The address answered, but not like an AI service. Check that it ends in /v1 "
     "(for Ollama: http://localhost:11434/v1)."),
    (ProviderError("boom"), "The provider returned an error: boom"),
])
def test_check_provider_messages(exc, expected):
    r = check_provider(FakeProvider(raises=exc, replies=["OK"]), "m")
    assert r.ok == (exc is None) and expected in r.message


def test_check_provider_sends_ping_with_small_budget():
    provider = FakeProvider(replies=["OK"])
    check_provider(provider, "some-model")
    call = provider.calls[0]
    assert call["model"] == "some-model"
    assert call["max_tokens"] == 20
    assert call["messages"] == [{"role": "user", "content": "Reply with the word OK."}]


def test_check_provider_unexpected_error_does_not_raise():
    r = check_provider(FakeProvider(raises=RuntimeError("bad thing")), "m")
    assert r == ConnectionResult(False, "Something went wrong: bad thing")


def test_check_search_success():
    search = FakeSearch()
    r = check_search(search)
    assert r == ConnectionResult(True, "Search is working.")
    assert search.queries == [("software engineer jobs", 1)]


def test_check_search_returns_search_error_message():
    r = check_search(FakeSearch(raises=SearchError("The search key was rejected")))
    assert r == ConnectionResult(False, "The search key was rejected")


def test_check_search_unexpected_error_does_not_raise():
    r = check_search(FakeSearch(raises=ValueError("nope")))
    assert r == ConnectionResult(False, "Something went wrong: nope")


def test_build_provider_reads_key():
    set_secret("provider:p1", "sk-1")
    p = build_provider(ProviderConfig(id="p1", kind="anthropic", label="Claude"))
    assert isinstance(p, AnthropicProvider)
    assert p._api_key == "sk-1"


def test_build_provider_openai_compatible_uses_base_url():
    set_secret("provider:local", "k")
    cfg = ProviderConfig(
        id="local", kind="openai_compatible", label="Ollama",
        base_url="http://127.0.0.1:11434/v1", structured_output="prompt",
    )
    p = build_provider(cfg)
    assert isinstance(p, OpenAICompatibleProvider)
    assert p._base_url == "http://127.0.0.1:11434/v1"
    assert p.supports_native_schema is False


def test_build_provider_unknown_kind_raises():
    cfg = ProviderConfig.model_construct(id="p", kind="bogus", label="x", base_url=None)
    with pytest.raises(ValueError):
        build_provider(cfg)


def test_build_search_without_key():
    with pytest.raises(SearchError, match="No search key"):
        build_search("tavily")


def test_build_search_reads_key():
    set_secret("search:tavily", "tv-1")
    assert isinstance(build_search("tavily"), TavilySearch)
    set_secret("search:brave", "br-1")
    assert isinstance(build_search("brave"), BraveSearch)


def test_build_search_builtin_is_rejected():
    with pytest.raises(ValueError, match="Built-in search has no separate key"):
        build_search("builtin")
