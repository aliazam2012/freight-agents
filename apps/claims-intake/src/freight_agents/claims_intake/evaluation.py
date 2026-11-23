"""Run the claims-intake golden set through the real workflow and gate it.

Modes: ``reference`` replays each case's scripted reference turns (checks the
pipeline, hooks and graders, not a model); ``recorded`` replays a real model's
recorded turns from ``evals/cassettes/<case>.jsonl``.
"""

from __future__ import annotations

import argparse
import tempfile
import time
import tomllib
from collections.abc import Callable
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
from freight_agents.llm import Model, ModelTurn, RecordingModel, ReplayModel, ScriptedModel

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
        started = time.perf_counter()
        view = intake.process(message)
        latency = time.perf_counter() - started
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
            cost_usd=None if intake.meter.unpriced else intake.meter.total_usd,
            tokens=sum(u.input_tokens + u.output_tokens for u in intake.meter.by_model.values()),
            latency_s=latency,
        )


def model_for(case: GoldenCase, mode: Mode, cassettes: Path, model_name: str) -> Model:
    if mode == "reference":
        return ScriptedModel(
            [ModelTurn.model_validate(t) for t in case.reference], name="reference"
        )
    return ReplayModel(cassettes / f"{case.id}.jsonl", name=model_name)


LiveModel = Callable[[GoldenCase], Model]


def record(
    cases: list[GoldenCase], total: int, live: LiveModel, cassettes: Path, root: Path, cap: float
) -> int:
    """Record live turns case by case; stop before spending more than the cap."""
    cassettes.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    for done, case in enumerate(cases, 1):
        path = cassettes / f"{case.id}.jsonl"
        path.unlink(missing_ok=True)
        run = run_case(case, RecordingModel(live(case), path), root)
        if run.cost_usd is None:
            print(f"{case.id}: the model has no known price; refusing to record blind")
            return 2
        spent += run.cost_usd
        print(f"{case.id:<28} {run.tokens:>7} tokens  ${run.cost_usd:.4f}  total ${spent:.4f}")
        if spent > cap:
            print(f"spending cap ${cap:.2f} reached after {done} cases; stopped")
            return 2
    if len(cases) < total:
        projected = spent / len(cases) * total
        print(f"${projected:.2f} projected for all {total} cases (from {len(cases)} recorded)")
    return 0


def main(argv: list[str] | None = None, live_model: LiveModel | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claims-eval")
    parser.add_argument("--mode", choices=["reference", "recorded", "record"], default="reference")
    parser.add_argument("--model-name", default="claude-opus-5-5")
    parser.add_argument("--limit", type=int, help="only the first N golden cases")
    parser.add_argument("--max-usd", type=float, default=0.0, help="record mode: spending cap")
    parser.add_argument("--cassettes", type=Path, help="recorded turns directory")
    parser.add_argument("--report", action="store_true", help="write a dated report")
    args = parser.parse_args(argv)
    root = repo_root()
    evals_dir = root / "apps" / "claims-intake" / "evals"
    cassettes = args.cassettes or evals_dir / "cassettes"
    every = load_cases(evals_dir / "golden.jsonl")
    cases = every[: args.limit] if args.limit else every

    if args.mode == "record":
        if args.max_usd <= 0:
            print("record mode spends money: pass --max-usd with the approved cap")
            return 2
        if live_model is None:
            from freight_agents.llm.anthropic_adapter import AnthropicModel

            def live_model(case: GoldenCase) -> Model:
                return AnthropicModel(model=args.model_name, effort="low")

        return record(cases, len(every), live_model, cassettes, root, args.max_usd)

    mode: Mode = args.mode
    label = "reference" if mode == "reference" else args.model_name
    result = run_suite(
        cases,
        lambda c: run_case(c, model_for(c, mode, cassettes, args.model_name), root),
        mode,
        label,
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
