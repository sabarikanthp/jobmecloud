import json

from fakes import FakeProvider, tool_reply
from jobmecloud.config.settings import Price
from jobmecloud.llm.loop import Tool, ToolError, run_agent
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.types import LLMResponse, ToolSpec, Usage


def make(prices_max=0.0):
    return CostTracker({"m": Price(input_per_mtok=1000, output_per_mtok=1000)}, max_usd=prices_max)


def echo_tool(log):
    def run(args):
        if args.get("bad"):
            raise ToolError("Bad input: give a name.")
        log.append(args)
        return "ok"

    return Tool(ToolSpec("echo", "Echo", {"type": "object", "properties": {}}), run)


def test_tool_result_goes_back_and_loop_ends():
    log = []
    p = FakeProvider(replies=[tool_reply(("echo", {"x": 1})), "all done"])
    r = run_agent(p, model="m", system="s", prompt="go", tools=[echo_tool(log)], costs=make())
    assert log == [{"x": 1}] and r.stop == "done" and r.text == "all done" and r.turns == 2
    assert p.calls[1]["messages"][-1] == {"role": "user", "content": ["ok"]}


def test_errors_go_back_to_the_model():
    p = FakeProvider(replies=[tool_reply(("nope", {}), ("echo", {"bad": True})), "done"])
    run_agent(p, model="m", system="s", prompt="go", tools=[echo_tool([])], costs=make())
    assert p.calls[1]["messages"][-1]["content"] == ["Unknown tool: nope", "Bad input: give a name."]


def test_unexpected_exception_is_generic():
    def boom(args):
        raise RuntimeError("secret detail")

    t = Tool(ToolSpec("boom", "Boom", {"type": "object"}), boom)
    p = FakeProvider(replies=[tool_reply(("boom", {})), "done"])
    run_agent(p, model="m", system="s", prompt="go", tools=[t], costs=make())
    assert p.calls[1]["messages"][-1]["content"] == ["The tool failed."]


def test_cost_cap_and_max_turns():
    p = FakeProvider(replies=[tool_reply(("echo", {}))] * 5)
    r = run_agent(p, model="m", system="s", prompt="go", tools=[echo_tool([])], costs=make(prices_max=0.01))
    assert r.stop == "cost_cap" and len(p.calls) == 1
    p = FakeProvider(replies=[tool_reply(("echo", {}))] * 5)
    assert run_agent(p, model="m", system="s", prompt="go", tools=[echo_tool([])], costs=make(), max_turns=3).stop == "max_turns"


def test_pause_continues_with_the_same_tools_every_turn():
    # The provider rejects a conversation whose earlier thinking blocks were made under a different
    # tools list, so the tools must not change between turns (the search budget is not a tool change).
    first = LLMResponse("", [], "pause", Usage(1, 1, web_searches=3), {"role": "assistant", "content": "..."})
    p = FakeProvider(replies=[first, LLMResponse("", [], "pause", Usage(1, 1, web_searches=1), {"role": "assistant", "content": "."}), "done"])
    run_agent(p, model="m", system="s", prompt="go", tools=[], costs=make(), builtin_search=True, max_searches=5)
    assert [c["max_searches"] for c in p.calls] == [5, 5, 5]
    assert [c["builtin_search"] for c in p.calls] == [True, True, True]
    assert len(p.calls[1]["messages"]) == 2  # user prompt + paused assistant turn, no new user message


def test_the_search_budget_ends_the_run_instead_of_changing_the_tools():
    paused = LLMResponse("found", [], "pause", Usage(1, 1, web_searches=3), {"role": "assistant", "content": "."})
    p = FakeProvider(replies=[paused, paused, "never reached"])
    r = run_agent(p, model="m", system="s", prompt="go", tools=[], costs=make(), builtin_search=True, max_searches=5)
    assert r.stop == "max_searches" and r.turns == 2 and len(p.calls) == 2
    assert r.text == "found"


def test_max_tokens_and_refusal_stop():
    for stop in ("max_tokens", "refusal"):
        reply = LLMResponse("x", [], stop, Usage(), {"role": "assistant", "content": "x"})
        r = run_agent(FakeProvider(replies=[reply]), model="m", system="s", prompt="go", tools=[], costs=make())
        assert r.stop == stop and r.turns == 1


def test_transcript_is_json_safe():
    class Block:
        def model_dump(self, mode):
            return {"type": "text", "text": "hi"}

    reply = LLMResponse("hi", [], "end", Usage(), {"role": "assistant", "content": [Block()]})
    r = run_agent(FakeProvider(replies=[reply]), model="m", system="s", prompt="go", tools=[], costs=make())
    json.dumps(r.transcript)
    assert r.transcript[-1]["content"] == [{"type": "text", "text": "hi"}]
