"""Model prices and the cost of a turn.

Prices are US dollars per million tokens, from Anthropic's published rates
(cached 2026-11-03). Cache-read prices appear only where published; when a
turn reads from the cache and its price is unknown, the cost is unknown
rather than guessed. Other providers' prices are passed in by the caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .types import Usage

MILLION = 1_000_000


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float | None = None
    # Some models charge a higher rate once the prompt passes a size.
    long_prompt_over: int | None = None
    long_input: float | None = None
    long_output: float | None = None


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.10),
    "claude-haiku-5-5": Price(
        input=0.10, output=0.50, long_prompt_over=100_000, long_input=0.50, long_output=2.50
    ),
}


def cost_usd(model: str, usage: Usage, prices: Mapping[str, Price] | None = None) -> float | None:
    price = (prices or PRICES).get(model)
    if price is None:
        return None
    if usage.cache_read_tokens and price.cache_read is None:
        return None
    in_rate, out_rate = price.input, price.output
    prompt = usage.input_tokens + usage.cache_read_tokens
    if price.long_prompt_over is not None and prompt > price.long_prompt_over:
        in_rate = price.long_input if price.long_input is not None else in_rate
        out_rate = price.long_output if price.long_output is not None else out_rate
    cache_rate = price.cache_read or 0.0
    total = (
        usage.input_tokens * in_rate
        + usage.output_tokens * out_rate
        + usage.cache_read_tokens * cache_rate
    )
    return total / MILLION
