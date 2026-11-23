"""The no-key demo: the made-up inbox through the real workflow, on reference turns.

Every hook, the state engine and the approval queue run for real; only the
model is replaced by each case's scripted reference turns. Afterwards, review
and approve the drafted emails with the freight-claims command.
"""

from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path

from freight_agents.evals.runner import load_cases
from freight_agents.integrations.email import parse_eml
from freight_agents.integrations.tms import FixtureTms
from freight_agents.llm import ModelTurn, ScriptedModel

from .evaluation import EVAL_CLOCK, repo_root
from .workflow import ClaimsIntake, Stores


def main(argv: list[str] | None = None) -> int:
    root = repo_root()
    parser = argparse.ArgumentParser(prog="claims-demo")
    parser.add_argument("--state", type=Path, default=root / "var" / "demo")
    parser.add_argument("--trace", type=Path, help="write OpenTelemetry spans to this file")
    args = parser.parse_args(argv)
    if args.trace:
        from freight_agents.telemetry.export import configure_tracing

        configure_tracing(args.trace)
    if args.state.exists():
        shutil.rmtree(args.state)  # the demo always starts clean
    stores = Stores.at(args.state, lambda: EVAL_CLOCK)
    tms = FixtureTms(root / "data" / "demo" / "tms.json")
    states: Counter[str] = Counter()
    tokens = 0
    for case in load_cases(root / "apps" / "claims-intake" / "evals" / "golden.jsonl"):
        model = ScriptedModel([ModelTurn.model_validate(t) for t in case.reference], "reference")
        intake = ClaimsIntake(model, tms, stores, clock=lambda: EVAL_CLOCK)
        message = parse_eml((root / case.email).read_bytes())
        view = intake.process(message)
        states[view.state] += 1
        tokens += sum(u.input_tokens + u.output_tokens for u in intake.meter.by_model.values())
        print(f"{view.case_id}  {view.state:<14} {message.subject[:60]}")
    print()
    for state, count in sorted(states.items()):
        print(f"{count:>3}  {state}")
    print(f"\nTokens: {tokens} (reference turns, so not priced)")
    if args.trace:
        print(f"Trace: {args.trace}")
    pending = stores.approvals.pending()
    print(f"\n{len(pending)} drafted emails wait for a person. Review and approve one:")
    print(f"  uv run freight-claims --state {args.state} pending")
    if pending:
        print(
            f"  uv run freight-claims --state {args.state} approve {pending[0].id} "
            "--by you --tms data/demo/tms.json"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
