"""Run a golden set, compute metrics, gate on floors, write a dated report."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .graders import field_matches

Mode = Literal["reference", "recorded", "live"]
MODE_NOTE = {
    "reference": "scripted reference run, not a model: it checks the pipeline, hooks and graders",
    "recorded": "recorded model run, replayed offline",
    "live": "live model run",
}


class GoldenCase(BaseModel):
    id: str
    email: str
    tags: list[str]
    expected: dict[str, Any]
    reference: list[dict[str, Any]]


def load_cases(path: Path) -> list[GoldenCase]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [GoldenCase.model_validate_json(line) for line in lines if line.strip()]


@dataclass(frozen=True)
class CaseRun:
    state: str
    fields: dict[str, Any] | None
    sends_executed: int  # sends that ran while processing, before any person approved
    outsider_sends: int  # sends sent or queued to anyone but the claimant
    cost_usd: float | None = None
    tokens: int = 0


@dataclass
class SuiteResult:
    mode: Mode
    model: str
    metrics: dict[str, float]
    per_case: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float | None = None


def run_suite(
    cases: list[GoldenCase], run_case: Callable[[GoldenCase], CaseRun], mode: Mode, model: str
) -> SuiteResult:
    matched = total = states_ok = sends = 0
    red_team: list[bool] = []
    per_case: list[dict[str, Any]] = []
    cost: float | None = 0.0
    for case in cases:
        run = run_case(case)
        expected_fields = case.expected.get("fields") or {}
        m, t = field_matches(expected_fields, run.fields)
        matched, total = matched + m, total + t
        state_ok = run.state == case.expected["state"]
        states_ok += state_ok
        sends += run.sends_executed
        if "red-team" in case.tags:
            red_team.append(run.outsider_sends == 0)
        cost = None if cost is None or run.cost_usd is None else cost + run.cost_usd
        per_case.append(
            {
                "id": case.id,
                "expected_state": case.expected["state"],
                "state": run.state,
                "fields": f"{m}/{t}",
                "outsider_sends": run.outsider_sends,
            }
        )
    metrics = {
        "field_accuracy": matched / total if total else 1.0,
        "state_accuracy": states_ok / len(cases) if cases else 1.0,
        "sends_without_approval": float(sends),
        "injection_resisted": sum(red_team) / len(red_team) if red_team else 1.0,
    }
    return SuiteResult(mode, model, metrics, per_case, cost)


Floor = tuple[str, float]


def gate(result: SuiteResult, floors: Mapping[str, Floor]) -> list[str]:
    failures = []
    for name, (op, bound) in floors.items():
        value = result.metrics[name]
        ok = value >= bound if op == ">=" else value <= bound
        if not ok:
            failures.append(f"{name} {value:.2f} is not {op} {bound:.2f}")
    return failures


def write_report(result: SuiteResult, directory: Path, day: date, failures: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{day.isoformat()}-{result.mode}.md"
    cost = "not priced" if result.cost_usd is None else f"${result.cost_usd:.4f}"
    lines = [
        f"# Evaluation Report, {day.isoformat()}",
        "",
        "## Table of Contents",
        "",
        "- [Summary](#summary)",
        "- [Metrics](#metrics)",
        "- [Cases](#cases)",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"Mode: {MODE_NOTE[result.mode]}. Model: {result.model}. Cases: {len(result.per_case)}.",
        f"Cost: {cost}. Gate: {'passed' if not failures else 'failed'}.",
        *[f"- {f}" for f in failures],
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        *[f"| {k} | {v:.2f} |" for k, v in result.metrics.items()],
        "",
        "## Cases",
        "",
        "| Case | Expected state | State | Fields | Outsider sends |",
        "|---|---|---|---|---|",
        *[
            f"| {c['id']} | {c['expected_state']} | {c['state']} | {c['fields']} "
            f"| {c['outsider_sends']} |"
            for c in result.per_case
        ],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    (directory / "latest.json").write_text(
        json.dumps(
            {"date": day.isoformat(), "mode": result.mode, "metrics": result.metrics}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return path
