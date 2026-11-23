import pytest
from freight_agents.llm import Usage, cost_usd


def test_opus_list_price() -> None:
    assert cost_usd("claude-opus-5-5", Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == (
        pytest.approx(24.0)
    )


def test_opus_cache_reads() -> None:
    assert cost_usd("claude-opus-5-5", Usage(cache_read_tokens=1_000_000)) == pytest.approx(0.20)


def test_haiku_short_prompt() -> None:
    usage = Usage(input_tokens=50_000, output_tokens=10_000)
    assert cost_usd("claude-haiku-5-5", usage) == pytest.approx(0.01)


def test_haiku_long_prompt_uses_the_higher_tier() -> None:
    usage = Usage(input_tokens=200_000, output_tokens=10_000)
    assert cost_usd("claude-haiku-5-5", usage) == pytest.approx(0.125)


def test_unknown_model_has_no_price() -> None:
    assert cost_usd("some-other-model", Usage(input_tokens=10)) is None


def test_unknown_cache_price_is_not_guessed() -> None:
    assert cost_usd("claude-haiku-5-5", Usage(input_tokens=10, cache_read_tokens=10)) is None
