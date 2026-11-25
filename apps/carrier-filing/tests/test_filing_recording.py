import tempfile
from pathlib import Path
from typing import Any

import pytest
from freight_agents.carrier_filing.desk import scripted_reply
from freight_agents.carrier_filing.evaluation import (
    FLOORS,
    model_read_scenarios,
    play_scenario,
    record,
    run_recorded,
    write_report,
)
from freight_agents.evals.recording import StaleCassette
from freight_agents.llm import Message, Model, ModelTurn, ScriptedModel, ToolSpec, Usage


class Capturing:
    def __init__(self, inner: Model, sink: list[ModelTurn]) -> None:
        self._inner, self._sink = inner, sink

    @property
    def name(self) -> str:
        return self._inner.name

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        turn = self._inner.complete(system, messages, tools)
        self._sink.append(turn)
        return turn


def live_reference(case_id: str) -> Model:
    """What the reference readers answer in this scenario, as one priced model."""
    (s,) = [x for x in model_read_scenarios(include_portal=False) if x.id == case_id]
    turns: list[ModelTurn] = []

    def reader(record: dict[str, Any], also: dict[str, Any] | None) -> Model:
        return Capturing(scripted_reply(record, also_send=also), turns)

    with tempfile.TemporaryDirectory() as tmp:
        play_scenario(s, Path(tmp), reader=reader)
    usage = Usage(input_tokens=2_500, output_tokens=200)
    priced = [t.model_copy(update={"model": "claude-opus-5-5", "usage": usage}) for t in turns]
    return ScriptedModel(priced, name="claude-opus-5-5")


@pytest.fixture(scope="module")
def cassettes(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("cassettes")
    result = record(out, live_reference, cap=20.0, include_portal=False)
    assert result.code == 0
    return out


def test_only_scenarios_that_read_carrier_replies_are_recorded(cassettes: Path) -> None:
    ids = {s.id for s in model_read_scenarios(include_portal=False)}
    assert ids
    assert {p.stem for p in cassettes.glob("*.jsonl")} == ids
    assert not any(s.attack for s in model_read_scenarios())
    assert all(s.channel != "api" for s in model_read_scenarios())


def test_recorded_mode_replays_through_the_same_gate(cassettes: Path) -> None:
    result = run_recorded(cassettes, "claude-opus-5-5", include_portal=False)
    assert result.failures(FLOORS) == []
    assert result.metrics["injection_resisted"] == 1.0  # red-team replies stay scripted


def test_a_missing_cassette_fails_recorded_mode_naming_the_scenario(
    cassettes: Path, tmp_path: Path
) -> None:
    victim, *rest = sorted(cassettes.glob("*.jsonl"))
    for path in rest:
        (tmp_path / path.name).write_bytes(path.read_bytes())
    with pytest.raises(StaleCassette, match=victim.stem):
        run_recorded(tmp_path, "claude-opus-5-5", include_portal=False)


def test_a_recorded_report_names_the_model(cassettes: Path, tmp_path: Path) -> None:
    result = run_recorded(cassettes, "claude-opus-5-5", include_portal=False)
    path = write_report(result, tmp_path, "2026-11-25", mode="recorded", model="claude-opus-5-5")
    assert path.name == "2026-11-25-recorded.md"
    assert "claude-opus-5-5" in path.read_text()


def test_the_eval_command_refuses_to_record_without_a_cap(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from freight_agents.carrier_filing.cli import main

    assert main(["eval", "--mode", "record", "--cassettes", str(tmp_path)]) == 2
    assert "--max-usd" in capsys.readouterr().out
