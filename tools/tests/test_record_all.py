import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from freight_agents.evals.recording import RecordResult

TOOLS = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


record_all = _load("record_all")


class Stub:
    """An app's recorder: spends what it is told, within the cap it is given."""

    def __init__(self, spend: float, projected: float | None = None, code: int = 0) -> None:
        self.spend, self.projected, self.code = spend, projected, code
        self.caps: list[float] = []
        self.limits: list[int | None] = []

    def __call__(self, live: Any, cap: float, limit: int | None, out: Any) -> RecordResult:
        self.caps.append(cap)
        self.limits.append(limit)
        spent = min(self.spend, cap)
        return RecordResult(code=self.code, spent=spent, projected=self.projected)


def test_one_cap_covers_every_app_in_turn() -> None:
    a, b = Stub(0.80), Stub(0.10)
    out: list[str] = []
    code = record_all.record_all(
        [("a", a), ("b", b)], cap=1.0, sample=None, live=None, out=out.append
    )
    assert code == 0
    assert a.caps == [1.0]
    assert b.caps[0] == 1.0 - 0.80
    assert "spent $0.90 now and $0.00 before, of the $1.00 cap" in out[-1]


def test_recording_stops_at_the_first_app_that_stops() -> None:
    a, b, c = Stub(0.50), Stub(0.40, code=2), Stub(0.10)
    out: list[str] = []
    code = record_all.record_all(
        [("a", a), ("b", b), ("c", c)], cap=1.0, sample=None, live=None, out=out.append
    )
    assert code == 2
    assert c.caps == []
    assert "stopped in b" in out[-1]


def test_a_sample_prints_each_apps_projection_and_the_total() -> None:
    a, b = Stub(0.30, projected=3.0), Stub(0.20, projected=1.5)
    out: list[str] = []
    record_all.record_all([("a", a), ("b", b)], cap=2.0, sample=3, live=None, out=out.append)
    assert a.limits == [3]
    assert any("a: $0.30 spent, $3.00 projected" in line for line in out)
    assert "$4.50 projected for every app" in out[-1]


def test_nothing_runs_without_an_approved_cap() -> None:
    a = Stub(0.10)
    out: list[str] = []
    assert record_all.record_all([("a", a)], cap=0.0, sample=3, live=None, out=out.append) == 2
    assert a.caps == []
    assert "--max-usd" in out[-1]


def test_every_app_is_in_the_recording() -> None:
    assert [name for name, _ in record_all.apps()] == [
        "claims-intake",
        "tms-orders",
        "carrier-filing",
        "incident-bot",
        "volume-forecast",
        "damage-assessor",
    ]


def test_every_real_recorder_reaches_its_app_and_refuses_an_unpriced_model(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from freight_agents.llm import ModelTurn, ScriptedModel, Usage

    monkeypatch.setattr(
        record_all, "CASSETTES", {name: tmp_path / name for name, _ in record_all.apps()}
    )

    def unpriced(case_id: str) -> Any:
        turn = ModelTurn(text="", tool_calls=[], stop="end", usage=Usage(), model="unpriced")
        return ScriptedModel([turn] * 50, name="unpriced")

    for name, recorder in record_all.apps():
        out: list[str] = []
        result = recorder(unpriced, 5.0, None, out.append)
        assert result.code == 2, name
        assert "no known price" in out[-1], (name, out[-3:])
        assert not list((tmp_path / name).glob("*.jsonl.part")), name


def test_what_each_app_already_recorded_counts_toward_the_one_cap() -> None:
    class Kept(Stub):
        def __call__(self, live: Any, cap: float, limit: int | None, out: Any) -> RecordResult:
            result = super().__call__(live, cap, limit, out)
            result.prior = 0.50
            return result

    a, b = Kept(0.20), Stub(0.10)
    out: list[str] = []
    record_all.record_all([("a", a), ("b", b)], cap=1.0, sample=None, live=None, out=out.append)
    assert b.caps[0] == pytest.approx(1.0 - 0.50 - 0.20)
    assert "spent $0.30 now and $0.50 before, of the $1.00 cap" in out[-1]
