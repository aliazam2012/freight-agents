from pathlib import Path

from freight_agents.claims_intake import evaluation
from freight_agents.evals.runner import GoldenCase
from freight_agents.llm import Model, ModelTurn, ScriptedModel, Usage


def _priced_reference(case: GoldenCase) -> Model:
    """The reference turns, dressed as a priced model with token counts."""
    turns = []
    for raw in case.reference:
        turn = ModelTurn.model_validate(raw)
        usage = Usage(input_tokens=2_000, output_tokens=300)
        turns.append(turn.model_copy(update={"model": "claude-opus-5-5", "usage": usage}))
    return ScriptedModel(turns, name="claude-opus-5-5")


def test_recording_writes_cassettes_that_replay_offline(tmp_path: Path) -> None:
    out = tmp_path / "cassettes"
    code = evaluation.main(
        ["--mode", "record", "--limit", "3", "--max-usd", "5", "--cassettes", str(out)],
        live_model=_priced_reference,
    )
    assert code == 0
    assert len(list(out.glob("*.jsonl"))) == 3
    replay = evaluation.main(
        ["--mode", "recorded", "--limit", "3", "--cassettes", str(out)],
    )
    assert replay == 0


def test_recording_stops_at_the_spending_cap(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "cassettes"
    code = evaluation.main(
        ["--mode", "record", "--max-usd", "0.10", "--cassettes", str(out)],
        live_model=_priced_reference,
    )
    assert code == 2
    assert len(list(out.glob("*.jsonl"))) < 36
    assert "spending cap" in capsys.readouterr().out


def test_a_sample_prints_the_projected_full_cost(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    evaluation.main(
        ["--mode", "record", "--limit", "2", "--max-usd", "5", "--cassettes", str(tmp_path / "c")],
        live_model=_priced_reference,
    )
    assert "projected for all 36 cases" in capsys.readouterr().out
