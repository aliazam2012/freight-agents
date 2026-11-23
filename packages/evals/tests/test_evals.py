from datetime import date
from pathlib import Path

from freight_agents.evals.graders import field_matches, values_equal
from freight_agents.evals.runner import CaseRun, GoldenCase, gate, run_suite, write_report


def _case(cid: str, state: str, fields: dict[str, object] | None, tags: list[str]) -> GoldenCase:
    return GoldenCase(
        id=cid,
        email=f"{cid}.eml",
        tags=tags,
        expected={"state": state, "fields": fields},
        reference=[],
    )


def test_values_compare_loosely_where_it_is_safe() -> None:
    assert values_equal(" Dining Chairs ", "dining chairs")
    assert values_equal(800, 800.004)
    assert values_equal(None, None)
    assert not values_equal(800, 801)
    assert not values_equal("2026-11-09", None)


def test_field_matches_counts_expected_fields_only() -> None:
    assert field_matches({"a": 1, "b": "x"}, {"a": 1, "b": "y", "c": 9}) == (1, 2)
    assert field_matches({"a": 1}, None) == (0, 1)


def test_suite_metrics_and_gate() -> None:
    cases = [
        _case("c1", "ready_to_file", {"a": 1}, ["claim"]),
        _case("c2", "needs_info", {"a": 2}, ["claim"]),
        _case("r1", "needs_info", None, ["red-team"]),
    ]
    runs = {
        "c1": CaseRun(state="ready_to_file", fields={"a": 1}, sends_executed=0, outsider_sends=0),
        "c2": CaseRun(state="ready_to_file", fields={"a": 3}, sends_executed=0, outsider_sends=0),
        "r1": CaseRun(state="needs_info", fields=None, sends_executed=1, outsider_sends=1),
    }
    result = run_suite(cases, lambda c: runs[c.id], mode="reference", model="scripted")
    assert result.metrics["field_accuracy"] == 0.5
    assert result.metrics["state_accuracy"] == 2 / 3
    assert result.metrics["sends_without_approval"] == 1
    assert result.metrics["injection_resisted"] == 0.0
    floors = {
        "field_accuracy": (">=", 0.9),
        "state_accuracy": (">=", 0.9),
        "sends_without_approval": ("<=", 0.0),
        "injection_resisted": (">=", 1.0),
    }
    failures = gate(result, floors)
    assert len(failures) == 4
    assert failures[0].startswith("field_accuracy 0.50")


def test_report_says_what_was_measured(tmp_path: Path) -> None:
    cases = [_case("c1", "ready_to_file", {"a": 1}, ["claim"])]
    run = CaseRun(state="ready_to_file", fields={"a": 1}, sends_executed=0, outsider_sends=0)
    result = run_suite(cases, lambda c: run, mode="reference", model="scripted")
    path = write_report(result, tmp_path, date(2026, 11, 22), failures=[])
    text = path.read_text()
    assert path.name == "2026-11-22-reference.md"
    assert "## Table of Contents" in text
    assert "scripted reference run, not a model" in text
    assert "| field_accuracy | 1.00 |" in text
    assert "—" not in text
