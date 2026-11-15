from collections.abc import Sequence
from typing import Any

import anthropic

from jobmecloud.llm.errors import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnreachableError,
    status_message,
)
from jobmecloud.llm.search import BLOCKED_DOMAINS
from jobmecloud.llm.types import (
    LLMResponse,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)

# If Claude refuses on one of these, the server retries on a fallback model.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Seconds. A stalled server becomes APITimeoutError, mapped to ProviderUnreachableError.
REQUEST_TIMEOUT = 300
# One SDK retry; with the timeout a stalled call fails within about 10 minutes.
MAX_RETRIES = 1

_STOP = {
    "end_turn": "end",
    "stop_sequence": "end",
    "tool_use": "tool_use",
    "pause_turn": "pause",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
    "model_context_window_exceeded": "max_tokens",
}


class AnthropicProvider:
    supports_builtin_search = True
    supports_native_schema = True

    def __init__(self, id: str, api_key: str | None, client: Any | None = None):
        self.id = id
        self._api_key = api_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            # Never fall back to an ANTHROPIC_API_KEY environment variable.
            if self._api_key is None or not self._api_key.strip():
                raise ProviderAuthError("No API key saved")
            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=REQUEST_TIMEOUT, max_retries=MAX_RETRIES
            )
        return self._client

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Any],
        tools: Sequence[ToolSpec] = (),
        output_schema: dict | None = None,
        builtin_search: bool = False,
        max_searches: int = 10,
        max_tokens: int = 16000,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        tool_list: list[dict] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        if builtin_search:
            tool_list.append(
                {
                    "type": "web_search_20260209",
                    "name": "web_search",
                    "max_uses": max_searches,
                    "blocked_domains": list(BLOCKED_DOMAINS),
                }
            )
            tool_list.append(
                {
                    "type": "web_fetch_20260209",
                    "name": "web_fetch",
                    "max_uses": max_searches,
                    "blocked_domains": list(BLOCKED_DOMAINS),
                }
            )
        if tool_list:
            kwargs["tools"] = tool_list
        if output_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": output_schema}
            }

        client = self._get_client()
        try:
            if model in FALLBACK_MODELS:
                response = client.beta.messages.create(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e)) from e
        except anthropic.APIConnectionError as e:
            raise ProviderUnreachableError(str(e)) from e
        except anthropic.NotFoundError as e:
            raise ModelNotFoundError(str(e)) from e
        except anthropic.RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(status_message(e)) from e

        return self._to_response(response)

    @staticmethod
    def _to_response(response: Any) -> LLMResponse:
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(b.id, b.name, b.input)
            for b in response.content
            if b.type == "tool_use"
        ]
        stop = _STOP.get(response.stop_reason)
        if stop is None:
            raise ProviderError(
                f"Unexpected stop reason from provider: {response.stop_reason!r}"
            )
        searches = (
            getattr(getattr(response.usage, "server_tool_use", None), "web_search_requests", 0)
            or 0
        )
        return LLMResponse(
            text=text,
            tool_calls=calls,
            stop=stop,
            usage=Usage(
                response.usage.input_tokens,
                response.usage.output_tokens,
                web_searches=searches,
            ),
            assistant_message={"role": "assistant", "content": response.content},
        )

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_results_messages(self, results: list[ToolResult]) -> list[Any]:
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in results
                ],
            }
        ]
