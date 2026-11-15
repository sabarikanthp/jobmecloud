import json
from collections.abc import Sequence
from typing import Any, Literal

import openai

from jobmecloud.llm.errors import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnreachableError,
    ProviderWrongAddressError,
    status_message,
)
from jobmecloud.llm.types import (
    LLMResponse,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)

# Seconds. A stalled server becomes APITimeoutError, mapped to ProviderUnreachableError.
REQUEST_TIMEOUT = 300
# One SDK retry; with the timeout a stalled call fails within about 10 minutes.
MAX_RETRIES = 1

_STOP = {
    "stop": "end",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "model_length": "max_tokens",
    "content_filter": "refusal",
}


def _error_text(e: openai.APIStatusError) -> str:
    return f"{e} {e.body}"


class OpenAICompatibleProvider:
    supports_builtin_search = False

    def __init__(
        self,
        id: str,
        api_key: str | None,
        base_url: str | None,
        structured_output: Literal["native", "prompt"] = "native",
        client: Any | None = None,
    ):
        self.id = id
        self._api_key = api_key
        self._base_url = base_url
        self.supports_native_schema = structured_output == "native"
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self._api_key or "not-needed",
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT,
                max_retries=MAX_RETRIES,
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
        if builtin_search:
            raise ValueError("This provider has no built-in search")
        # max_tokens is deliberately not sent: some OpenAI models reject it and
        # local servers enforce their own limits.
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        if output_schema is not None and self.supports_native_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": output_schema, "strict": True},
            }

        client = self._get_client()
        try:
            response = client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as e:
            raise ProviderAuthError(str(e)) from e
        except openai.APIConnectionError as e:
            raise ProviderUnreachableError(str(e)) from e
        except openai.NotFoundError as e:
            if "model" in _error_text(e).lower():
                raise ModelNotFoundError(str(e)) from e
            raise ProviderWrongAddressError(str(e)) from e
        except openai.RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except openai.APIStatusError as e:
            raise ProviderError(status_message(e)) from e

        return self._to_response(response)

    @staticmethod
    def _to_response(response: Any) -> LLMResponse:
        if not response.choices:
            raise ProviderError("The provider returned no answer.")
        choice = response.choices[0]
        message = choice.message
        calls = []
        for tc in message.tool_calls or []:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as e:
                raise ProviderError(
                    f"Provider returned invalid JSON arguments for tool {tc.function.name!r}"
                ) from e
            calls.append(ToolCall(tc.id, tc.function.name, arguments))
        if calls:
            stop = "tool_use"
        else:
            stop = _STOP.get(choice.finish_reason, "end")
        assistant_message: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            # Sent back exactly as received so provider extras (e.g. Gemini's
            # thought signature in extra_content) survive.
            assistant_message["tool_calls"] = [
                tc.model_dump(exclude_none=True) for tc in message.tool_calls
            ]
        usage = response.usage
        return LLMResponse(
            text=message.content or "",
            tool_calls=calls,
            stop=stop,
            usage=Usage(
                (usage.prompt_tokens or 0) if usage else 0,
                (usage.completion_tokens or 0) if usage else 0,
            ),
            assistant_message=assistant_message,
        )

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_results_messages(self, results: list[ToolResult]) -> list[Any]:
        return [
            {
                "role": "tool",
                "tool_call_id": r.call_id,
                "content": f"ERROR: {r.content}" if r.is_error else r.content,
            }
            for r in results
        ]
