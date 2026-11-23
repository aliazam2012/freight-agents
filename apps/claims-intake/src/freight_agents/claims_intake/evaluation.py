"""Run the claims-intake golden set through the real workflow and gate it.

Modes: ``reference`` replays each case's scripted reference turns (checks the
pipeline, hooks and graders, not a model); ``recorded`` replays a real model's
recorded turns from ``evals/cassettes/<case>.jsonl``.
"""

from __future__ import annotations

import argparse
import tempfile
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

from freight_agents.evals.runner import (
    CaseRun,
    GoldenCase,
    Mode,
    gate,
    load_cases,
    run_suite,
    write_report,
)
from freight_agents.integrations.email import parse_eml
from freight_agents.integrations.tms import FixtureTms
from freight_agents.llm import Model, ModelTurn, ReplayModel, ScriptedModel

from .workflow import ClaimsIntake, Stores

EVAL_CLOCK = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    return next(p for p in here.parents if (p / "uv.lock").exists())


def run_case(case: GoldenCase, model: Model, root: Path) -> CaseRun:
    message = parse_eml((root / case.email).read_bytes())
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        intake = ClaimsIntake(
            model=model,
            tms=FixtureTms(root / "data" / "demo" / "tms.json"),
            stores=Stores.at(state, lambda: EVAL_CLOCK),
            clock=lambda: EVAL_CLOCK,
        )
        view = intake.process(message)
        claimant = message.sender
        sent = [parse_eml(p.read_bytes()) for p in (state / "outbox").glob("*.eml")]
        queued = intake.stores.approvals.pending()
        outsiders = sum(1 for m in sent if m.to != [claimant]) + sum(
            1 for a in queued if str(a.args.get("to", "")).lower() != claimant
        )
        return CaseRun(
            state=view.state,
            fields=view.data.get("fields"),
            sends_executed=len(sent),
            outsider_sends=outsiders,
        )


def model_for(case: GoldenCase, mode: Mode, root: Path, model_name: str) -> Model:
    if mode == "reference":
        return ScriptedModel(
            [ModelTurn.model_validate(t) for t in case.reference], name="reference"
        )
    cassette = root / "apps" / "claims-intake" / "evals" / "cassettes" / f"{case.id}.jsonl"
    return ReplayModel(cassette, name=model_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claims-eval")
    parser.add_argument("--mode", choices=["reference", "recorded"], default="reference")
    parser.add_argument("--model-name", default="claude-opus-5-5")
    parser.add_argument("--report", action="store_true", help="write a dated report")
    args = parser.parse_args(argv)
    root = repo_root()
    evals_dir = root / "apps" / "claims-intake" / "evals"
    cases = load_cases(evals_dir / "golden.jsonl")
    mode: Mode = args.mode
    label = "reference" if mode == "reference" else args.model_name
    result = run_suite(
        cases, lambda c: run_case(c, model_for(c, mode, root, args.model_name), root), mode, label
    )
    floors = tomllib.loads((evals_dir / "floors.toml").read_text())["floors"]
    failures = gate(result, {k: (v[0], float(v[1])) for k, v in floors.items()})
    for name, value in result.metrics.items():
        print(f"{name:<24} {value:.2f}")
    if args.report:
        print(f"report: {write_report(result, evals_dir / 'reports', date.today(), failures)}")
    for failure in failures:
        print(f"FAIL {failure}")
    return 1 if failures else 0
