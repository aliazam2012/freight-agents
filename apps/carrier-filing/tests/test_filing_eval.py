from pathlib import Path
from typing import Any

import pytest
from freight_agents.carrier_filing import channels
from freight_agents.carrier_filing.evaluation import FLOORS, run, scenarios, write_report


def test_there_are_at_least_thirty_scenarios_with_faults_and_attacks() -> None:
    all_ = scenarios()
    assert len(all_) >= 30
    assert {s.channel for s in all_} == {"api", "portal", "email"}
    assert sum(1 for s in all_ if s.fault) >= 7
    assert sum(1 for s in all_ if s.attack) == 3


def test_the_reference_run_passes_the_gate(tmp_path: Path) -> None:
    result = run()
    broken = [
        r
        for r in result.per_case
        if not (
            r["filings_ok"]
            and r["followups_ok"]
            and r["state"] == r["expected_state"]
            and r["resisted"] is not False
        )
    ]
    assert result.failures(FLOORS) == [], broken
    path = write_report(result, tmp_path, "2026-11-24")
    assert "Gate: passed" in path.read_text()


def test_the_grader_catches_a_double_filing(monkeypatch: pytest.MonkeyPatch) -> None:
    def never_found(self: Any, reference: str) -> Any:
        return None

    monkeypatch.setattr(channels.ApiChannel, "find", never_found)
    result = run(include_portal=False)
    assert result.metrics["filings_exact"] < 1.0
