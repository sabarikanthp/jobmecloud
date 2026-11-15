"""The agent loop, written by hand.

An "agent" is a loop around one idea: the model cannot run code, but it can ask
us to. Each turn we send the conversation so far; the model answers with text,
or with a request to call one of our tools. We run the tool, append the result
to the conversation, and ask again. We stop when the model says it is done, or
when a safety limit (turns, money, tokens) is reached.

No agent framework and no SDK tool runner: this file is the whole mechanism.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.types import Provider, ToolResult, ToolSpec

MAX_TURNS = 40


class ToolError(Exception):
    """Raised by a tool; the message is sent back to the model as an error result."""


@dataclass
class Tool:
    spec: ToolSpec  # what the model sees: name, description, input schema
    run: Callable[[dict], str]  # what we execute when the model calls it


@dataclass
class AgentResult:
    stop: Literal["done", "max_turns", "cost_cap", "max_searches", "max_tokens", "refusal"]
    text: str  # last assistant text
    turns: int  # number of provider calls
    transcript: list  # JSON-safe record of the conversation


def to_jsonable(value: Any) -> Any:
    """Make provider-native messages safe to store as JSON."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    return str(value)


def run_agent(
    provider: Provider,
    *,
    model: str,
    system: str,
    prompt: str,
    tools: Sequence[Tool],
    costs: CostTracker,
    builtin_search: bool = False,
    max_searches: int = 0,
    max_turns: int = MAX_TURNS,
) -> AgentResult:
    # 1. The conversation starts with the user's prompt.
    first = provider.user_message(prompt)
    messages: list[Any] = [first]
    transcript: list = [to_jsonable(first)]
    by_name = {t.spec.name: t for t in tools}
    turns = 0
    searches_used = 0  # built-in searches used by this agent call only
    text = ""

    while True:
        # 2. Before each turn, check the safety limits, then ask the model.
        if costs.exceeded:
            return AgentResult("cost_cap", text, turns, transcript)
        if turns == max_turns:
            return AgentResult("max_turns", text, turns, transcript)
        # The tools are identical on every turn: the provider rejects a conversation whose earlier
        # thinking blocks were made under a different tools list. The search budget is therefore
        # enforced below by ending the run, never by changing what the model is offered.
        resp = provider.complete(
            model=model,
            system=system,
            messages=messages,
            tools=[t.spec for t in tools],
            builtin_search=builtin_search,
            max_searches=max_searches,
        )
        turns += 1

        # 3. Record the reply: bill it, and keep the model's message exactly as
        #    given so the next turn can see it.
        costs.add(model, resp.usage)
        searches_used += resp.usage.web_searches
        text = resp.text
        messages.append(resp.assistant_message)
        transcript.append(to_jsonable(resp.assistant_message))

        # 4. Act on why the model stopped.
        if resp.stop == "tool_use":
            # The model asked for tools: run each, turning failures into
            # results the model can read and react to.
            results: list[ToolResult] = []
            for call in resp.tool_calls:
                tool = by_name.get(call.name)
                if tool is None:
                    results.append(ToolResult(call.id, f"Unknown tool: {call.name}", is_error=True))
                    continue
                try:
                    results.append(ToolResult(call.id, tool.run(call.arguments)))
                except ToolError as e:
                    results.append(ToolResult(call.id, str(e), is_error=True))
                except Exception:
                    results.append(ToolResult(call.id, "The tool failed.", is_error=True))
            new_messages = provider.tool_results_messages(results)
            messages.extend(new_messages)
            transcript.extend(to_jsonable(m) for m in new_messages)
        elif resp.stop == "pause":
            # The provider is mid-way through its own server-side tool work
            # (e.g. built-in search); send the conversation back to resume it,
            # unless the search budget is already spent.
            if builtin_search and searches_used >= max_searches:
                return AgentResult("max_searches", text, turns, transcript)
            continue
        elif resp.stop == "end":
            return AgentResult("done", text, turns, transcript)
        else:  # "max_tokens" or "refusal"
            return AgentResult(resp.stop, text, turns, transcript)
