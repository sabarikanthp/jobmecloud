import pytest

from jobmecloud.config.settings import Price, Settings
from jobmecloud.llm.pricing import CostTracker, estimate_cost
from jobmecloud.llm.types import Usage


def test_cost_known_model():
    prices = Settings().prices
    assert estimate_cost("claude-sonnet-5-5", Usage(1_000_000, 100_000), prices) == pytest.approx(3.0)


def test_cost_unknown_model_is_zero():
    assert estimate_cost("llama3.1:8b", Usage(5000, 5000), Settings().prices) == 0.0


def test_cost_tracker_sums_and_caps():
    prices = {"m": Price(input_per_mtok=1, output_per_mtok=10)}
    t = CostTracker(prices, max_usd=0.02)
    t.add("m", Usage(1_000_000 // 100, 1000))
    assert (t.input_tokens, t.output_tokens) == (10_000, 1000)
    assert t.cost == pytest.approx(0.02) and t.exceeded
    t2 = CostTracker(prices, max_usd=0)
    t2.add("unknown-model", Usage(5, 5, web_searches=2))
    assert t2.cost == pytest.approx(0.02) and not t2.exceeded
