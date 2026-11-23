"""Running token and dollar totals for a run or a whole evaluation."""

from __future__ import annotations

from collections.abc import Mapping

from freight_agents.llm import Price, Usage, cost_usd


class CostMeter:
    def __init__(self, prices: Mapping[str, Price] | None = None) -> None:
        self._prices = prices
        self.by_model: dict[str, Usage] = {}
        self.unpriced: set[str] = set()
        self.total_usd = 0.0

    def add(self, model: str, usage: Usage) -> float | None:
        self.by_model[model] = self.by_model.get(model, Usage()) + usage
        cost = cost_usd(model, usage, self._prices)
        if cost is None:
            self.unpriced.add(model)
        else:
            self.total_usd += cost
        return cost
