from pathlib import Path

import pytest
from freight_agents.evals.recording import record_cases
from freight_agents.llm import Message, Model, ModelTurn, ScriptedModel, TextPart, Usage

FORTY_CENTS = Usage(input_tokens=100_000, output_tokens=0)  # $0.40 on claude-opus-5-5


def priced(name: str = "claude-opus-5-5") -> Model:
    turn = ModelTurn(text="ok", tool_calls=[], stop="end", usage=FORTY_CENTS, model=name)
    return ScriptedModel([turn], name=name)


def run_one(case_id: str, model: Model) -> None:
    model.complete("system", [Message(role="user", parts=[TextPart(text=case_id)])], [])


def lines() -> tuple[list[str], object]:
    out: list[str] = []
    return out, out.append


def test_recording_refuses_to_start_without_an_approved_cap(tmp_path: Path) -> None:
    out, say = lines()
    calls: list[str] = []
    result = record_cases(
        ["a"], run_one, lambda c: calls.append(c) or priced(), tmp_path, 0.0, out=say
    )
    assert result.code == 2
    assert calls == []
    assert "--max-usd" in out[-1]


def test_recording_refuses_a_model_with_no_known_price(tmp_path: Path) -> None:
    out, say = lines()
    result = record_cases(["a"], run_one, lambda c: priced("mystery-model"), tmp_path, 5.0, out=say)
    assert result.code == 2
    assert not (tmp_path / "a.jsonl").exists()
    assert "no known price" in out[-1]


def test_recording_stops_before_a_case_that_could_pass_the_cap(tmp_path: Path) -> None:
    out, say = lines()
    result = record_cases(["a", "b", "c"], run_one, lambda c: priced(), tmp_path, 1.0, out=say)
    assert result.code == 2
    assert result.spent == pytest.approx(0.80)  # a and b; c would make 1.20
    assert sorted(p.name for p in tmp_path.glob("*.jsonl")) == ["a.jsonl", "b.jsonl"]
    assert "before c" in out[-1]


def test_an_interrupted_recording_resumes_without_paying_again(tmp_path: Path) -> None:
    record_cases(["a"], run_one, lambda c: priced(), tmp_path, 5.0, out=lambda s: None)
    called: list[str] = []

    def live(case_id: str) -> Model:
        called.append(case_id)
        return priced()

    result = record_cases(["a", "b"], run_one, live, tmp_path, 5.0, out=lambda s: None)
    assert called == ["b"]
    assert result.spent == pytest.approx(0.40)
    assert result.kept == ["a"]


def test_a_case_that_fails_mid_recording_leaves_no_cassette(tmp_path: Path) -> None:
    def broken(case_id: str, model: Model) -> None:
        run_one(case_id, model)
        raise RuntimeError("the app crashed after the model answered")

    out, say = lines()
    result = record_cases(["a"], broken, lambda c: priced(), tmp_path, 5.0, out=say)
    assert result.code == 2
    assert list(tmp_path.iterdir()) == []
    assert "RuntimeError" in out[-1]


def test_a_sample_projects_the_cost_of_the_whole_set(tmp_path: Path) -> None:
    out, say = lines()
    result = record_cases(
        ["a", "b", "c"], run_one, lambda c: priced(), tmp_path, 5.0, total=10, out=say
    )
    assert result.code == 0
    assert result.projected == pytest.approx(4.00)
    assert "$4.00 projected for all 10 cases" in out[-1]


def test_replay_names_the_case_whose_cassette_is_stale_or_missing(tmp_path: Path) -> None:
    from freight_agents.evals.recording import StaleCassette, replay

    record_cases(["a"], run_one, lambda c: priced(), tmp_path, 5.0, out=lambda s: None)
    replay("a", tmp_path, "claude-opus-5-5", run_one)  # same request: replays
    changed = lambda case_id, model: run_one(case_id + " with a new prompt", model)  # noqa: E731
    with pytest.raises(StaleCassette, match=r"a: .*re-record"):
        replay("a", tmp_path, "claude-opus-5-5", changed)
    with pytest.raises(StaleCassette, match="b: no cassette"):
        replay("b", tmp_path, "claude-opus-5-5", run_one)


def test_a_replay_model_names_its_case_when_the_request_changed(tmp_path: Path) -> None:
    from freight_agents.evals.recording import StaleCassette, replay_model

    record_cases(["a"], run_one, lambda c: priced(), tmp_path, 5.0, out=lambda s: None)
    model = replay_model("a", tmp_path, "claude-opus-5-5")
    run_one("a", model)
    with pytest.raises(StaleCassette, match="a: "):
        run_one("a, changed", model)
    with pytest.raises(StaleCassette, match="b: no cassette"):
        replay_model("b", tmp_path, "claude-opus-5-5")


def test_a_case_that_never_calls_the_model_records_an_empty_cassette(tmp_path: Path) -> None:
    from freight_agents.evals.recording import replay

    result = record_cases(
        ["quiet"], lambda c, m: None, lambda c: priced(), tmp_path, 5.0, out=lambda s: None
    )
    assert result.code == 0
    assert (tmp_path / "quiet.jsonl").read_text() == ""
    assert replay("quiet", tmp_path, "claude-opus-5-5", lambda c, m: "no calls") == "no calls"


def test_cassettes_already_recorded_count_toward_the_cap(tmp_path: Path) -> None:
    # The sample's spending is part of the approved total, and its costliest case is
    # the estimate for the next one.
    record_cases(["a"], run_one, lambda c: priced(), tmp_path, 5.0, out=lambda s: None)
    out: list[str] = []
    result = record_cases(["a", "b"], run_one, lambda c: priced(), tmp_path, 0.60, out=out.append)
    assert result.code == 2
    assert result.prior == pytest.approx(0.40)
    assert result.spent == 0.0
    assert not (tmp_path / "b.jsonl").exists()
    assert "before b" in out[-1]
