from jobmecloud.config.settings import Price
from jobmecloud.llm.types import Usage

# Flat USD price of one built-in web search, charged on top of token costs.
BUILTIN_SEARCH_USD = 0.01


def estimate_cost(model: str, usage: Usage, prices: dict[str, Price]) -> float:
    search_cost = usage.web_searches * BUILTIN_SEARCH_USD
    price = prices.get(model)
    if price is None:
        return search_cost
    return (
        usage.input_tokens / 1e6 * price.input_per_mtok
        + usage.output_tokens / 1e6 * price.output_per_mtok
        + search_cost
    )


class CostTracker:
    """Accumulates token, search and USD totals for one run."""

    def __init__(self, prices: dict[str, Price], max_usd: float):
        self._prices = prices
        self._max_usd = max_usd
        self.input_tokens = 0
        self.output_tokens = 0
        self.web_searches = 0
        self.cost = 0.0

    def add(self, model: str, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.web_searches += usage.web_searches
        self.cost += estimate_cost(model, usage, self._prices)

    @property
    def exceeded(self) -> bool:
        return self._max_usd > 0 and self.cost >= self._max_usd
