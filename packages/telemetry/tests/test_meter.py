import pytest
from freight_agents.llm import Usage
from freight_agents.telemetry.meter import CostMeter


def test_meter_sums_priced_models_and_lists_unpriced_ones() -> None:
    meter = CostMeter()
    meter.add("claude-opus-5-5", Usage(input_tokens=1_000_000))
    meter.add("claude-sonnet-5-5", Usage(output_tokens=1_000_000))
    meter.add("other-model", Usage(input_tokens=10))
    assert meter.total_usd == pytest.approx(14.0)
    assert meter.unpriced == {"other-model"}
    assert meter.by_model["claude-opus-5-5"].input_tokens == 1_000_000
