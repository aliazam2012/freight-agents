import json
from pathlib import Path

import pytest
from freight_agents.evals.recording import StaleCassette
from freight_agents.llm import Message, Model, ModelTurn, ToolSpec, Usage
from freight_agents.tms_orders.evaluation import (
    FLOORS,
    model_read_cases,
    record,
    run_recorded,
)
from freight_agents.tms_orders.fixtures import write_fixtures
from freight_agents.tms_orders.workflow import reference_models


class PricedAs:
    """The reference model, dressed as a priced live model with token counts."""

    def __init__(self, inner: Model) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return "claude-opus-5-5"

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        turn = self._inner.complete(system, messages, tools)
        usage = Usage(input_tokens=3_000, output_tokens=400)
        return turn.model_copy(update={"model": "claude-opus-5-5", "usage": usage})


@pytest.fixture(scope="module")
def inbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tenders")
    write_fixtures(root)
    return root


@pytest.fixture(scope="module")
def cassettes(inbox: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("cassettes")
    reference = reference_models(inbox / "gold.jsonl")
    result = record(inbox, out, lambda path: PricedAs(reference(path)), cap=20.0)
    assert result.code == 0
    return out


def test_only_tenders_the_model_reads_are_recorded(inbox: Path, cassettes: Path) -> None:
    cases = model_read_cases(inbox)
    gold = [json.loads(line) for line in (inbox / "gold.jsonl").read_text().splitlines()]
    edi = {row["id"] for row in gold if row["source"] == "edi"}
    assert edi
    assert not edi & set(cases.values())
    assert {p.stem for p in cassettes.glob("*.jsonl")} == set(cases.values())
    assert any(case_id.startswith("redteam-") for case_id in cases.values())


def test_recorded_mode_replays_the_cassettes_through_the_same_gate(
    inbox: Path, cassettes: Path
) -> None:
    result = run_recorded(inbox, cassettes, "claude-opus-5-5")
    assert result.failures(FLOORS) == []
    assert result.metrics["cases"] == 36


def test_a_missing_cassette_fails_recorded_mode_naming_the_tender(
    inbox: Path, cassettes: Path, tmp_path: Path
) -> None:
    partial = tmp_path / "partial"
    partial.mkdir()
    (victim, *rest) = sorted(cassettes.glob("*.jsonl"))
    for path in rest:
        (partial / path.name).write_bytes(path.read_bytes())
    with pytest.raises(StaleCassette, match=victim.stem):
        run_recorded(inbox, partial, "claude-opus-5-5")


def test_a_sample_projects_the_cost_of_every_model_read_tender(inbox: Path, tmp_path: Path) -> None:
    reference = reference_models(inbox / "gold.jsonl")
    result = record(
        inbox, tmp_path, lambda path: PricedAs(reference(path)), cap=5.0, limit=2, out=print
    )
    assert result.code == 0
    assert len(result.recorded) == 2
    assert result.projected is not None
    assert result.projected > result.spent


def test_the_eval_command_refuses_to_record_without_a_cap(
    inbox: Path, tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    from freight_agents.tms_orders.cli import main

    code = main(["eval", "--mode", "record", "--inbox", str(inbox), "--cassettes", str(tmp_path)])
    assert code == 2
    assert "--max-usd" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_the_eval_command_names_a_missing_cassette(inbox: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from freight_agents.tms_orders.cli import main

    args = ["eval", "--mode", "recorded", "--inbox", str(inbox), "--cassettes", str(tmp_path)]
    assert main([*args, "--reports", str(tmp_path / "r")]) == 2
    assert "no cassette" in capsys.readouterr().out


def test_a_recorded_report_names_the_model_and_its_mode(
    inbox: Path, cassettes: Path, tmp_path: Path
) -> None:
    from freight_agents.tms_orders.evaluation import write_report

    result = run_recorded(inbox, cassettes, "claude-opus-5-5")
    path = write_report(result, tmp_path, "2026-11-25", mode="recorded", model="claude-opus-5-5")
    assert path.name == "2026-11-25-recorded.md"
    text = path.read_text()
    assert "recorded turns of claude-opus-5-5" in text
    assert "reference mode" not in text
    assert json.loads((tmp_path / "latest.json").read_text())["mode"] == "recorded"
