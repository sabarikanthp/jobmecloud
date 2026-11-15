from dataclasses import dataclass

from jobmecloud.llm.errors import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnreachableError,
    ProviderWrongAddressError,
)
from jobmecloud.llm.search import SearchBackend, SearchError
from jobmecloud.llm.structured import StructuredOutputError
from jobmecloud.llm.types import Provider


@dataclass
class ConnectionResult:
    ok: bool
    message: str


def friendly_message(e: Exception) -> str:
    if isinstance(e, ProviderAuthError):
        return "The API key was rejected. Check that you copied the whole key."
    if isinstance(e, ProviderUnreachableError):
        return (
            "Couldn't reach the provider. Check the address, your internet connection, "
            "or that your local model server is running."
        )
    if isinstance(e, ModelNotFoundError):
        return "Connected, but the model name wasn't found. Check the spelling."
    if isinstance(e, ProviderWrongAddressError):
        return (
            "The address answered, but not like an AI service. Check that it ends in /v1 "
            "(for Ollama: http://localhost:11434/v1)."
        )
    if isinstance(e, ProviderRateLimitError):
        return (
            "Connected, but the provider says you're over your limit. "
            "Try again later or check your plan."
        )
    if isinstance(e, StructuredOutputError):
        return "The AI's answer couldn't be used. Try again, or fill in the form yourself."
    if isinstance(e, ProviderError):
        return f"The provider returned an error: {e}"
    return f"Something went wrong: {e}"


def check_provider(provider: Provider, model: str) -> ConnectionResult:
    try:
        provider.complete(
            model=model,
            system="You are a connection test.",
            messages=[provider.user_message("Reply with the word OK.")],
            max_tokens=20,
        )
    except Exception as e:
        return ConnectionResult(False, friendly_message(e))
    return ConnectionResult(True, "Connected. The model replied.")


def check_search(backend: SearchBackend) -> ConnectionResult:
    try:
        backend.search("software engineer jobs", max_results=1)
    except SearchError as e:
        return ConnectionResult(False, str(e))
    except Exception as e:
        return ConnectionResult(False, f"Something went wrong: {e}")
    return ConnectionResult(True, "Search is working.")
