from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop: Literal["end", "tool_use", "pause", "max_tokens", "refusal"]
    usage: Usage
    # Provider-native message; the agent loop appends it unchanged so Claude's
    # server-tool and thinking blocks stay intact.
    assistant_message: Any


class Provider(Protocol):
    id: str
    supports_builtin_search: bool
    supports_native_schema: bool

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
    ) -> LLMResponse: ...

    def user_message(self, text: str) -> Any: ...

    def tool_results_messages(self, results: list[ToolResult]) -> list[Any]: ...
