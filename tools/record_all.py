"""Record every app's evaluation on a real model, under one spending cap.

Spends money. Run a sample first and read the projection:

    uv run --all-packages python tools/record_all.py --sample 3 --max-usd 2

Each app records its first three cases and prints what they cost and what all of its
cases would cost. With the owner's approval of that projection, record everything:

    uv run --all-packages python tools/record_all.py --max-usd <approved cap>

The apps run in turn, each under what is left of the one cap; recording stops at the
first app that stops (the cap, an unpriced model, a failed case). Cassettes already
recorded are kept and never paid for again, so a stopped run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from freight_agents.evals.recording import RecordResult, record_cases
from freight_agents.llm import Model

ROOT = Path(__file__).resolve().parent.parent
Live = Callable[[str], Model]
Recorder = Callable[[Any, float, int | None, Callable[[str], object]], RecordResult]
NAMES = (
    "claims-intake",
    "tms-orders",
    "carrier-filing",
    "incident-bot",
    "volume-forecast",
    "damage-assessor",
)
CASSETTES = {name: ROOT / "apps" / name / "evals" / "cassettes" for name in NAMES}


def _claims(
    live: Live, cap: float, limit: int | None, out: Callable[[str], object]
) -> RecordResult:
    from freight_agents.claims_intake import evaluation
    from freight_agents.evals.runner import load_cases

    every = load_cases(ROOT / "apps" / "claims-intake" / "evals" / "golden.jsonl")
    by_id = {case.id: case for case in (every[:limit] if limit else every)}
    return record_cases(
        list(by_id),
        lambda case_id, model: evaluation.run_case(by_id[case_id], model, ROOT),
        live,
        CASSETTES["claims-intake"],
        cap,
        total=len(every),
        out=out,
    )


def _orders(
    live: Live, cap: float, limit: int | None, out: Callable[[str], object]
) -> RecordResult:
    from freight_agents.tms_orders.evaluation import record

    cassettes = CASSETTES["tms-orders"]
    return record(
        ROOT / "data" / "tenders", cassettes, lambda path: live(path.stem), cap, limit, out
    )


def _filing(
    live: Live, cap: float, limit: int | None, out: Callable[[str], object]
) -> RecordResult:
    from freight_agents.carrier_filing.evaluation import record

    return record(CASSETTES["carrier-filing"], live, cap, limit, out=out)


def _incidents(
    live: Live, cap: float, limit: int | None, out: Callable[[str], object]
) -> RecordResult:
    from freight_agents.incident_bot.evaluation import record

    return record(CASSETTES["incident-bot"], live, cap, limit, out)


def _forecast(
    live: Live, cap: float, limit: int | None, out: Callable[[str], object]
) -> RecordResult:
    from freight_agents.volume_forecast.evaluation import (
        QUESTIONS,
        load_cases,
        record,
        reference_deps,
    )

    cases, deps = load_cases(QUESTIONS), reference_deps()
    return record(cases, deps, CASSETTES["volume-forecast"], live, cap, limit, out)


def _damage(
    live: Live, cap: float, limit: int | None, out: Callable[[str], object]
) -> RecordResult:
    from freight_agents.damage_assessor.evaluation import record

    return record(ROOT / "data" / "damage", CASSETTES["damage-assessor"], live, cap, limit, out)


def apps() -> list[tuple[str, Recorder]]:
    recorders: list[Recorder] = [_claims, _orders, _filing, _incidents, _forecast, _damage]
    return list(zip(NAMES, recorders, strict=True))


def record_all(
    recorders: list[tuple[str, Recorder]],
    cap: float,
    sample: int | None,
    live: Any,
    out: Callable[[str], object] = print,
) -> int:
    """Each app in turn under what is left of one cap; stop at the first app that stops."""
    if cap <= 0:
        out("recording spends money: pass --max-usd with the approved cap")
        return 2
    spent = projected = 0.0
    for name, recorder in recorders:
        result = recorder(live, cap - spent, sample, lambda line, n=name: out(f"[{n}] {line}"))
        spent += result.spent
        whole = result.projected if result.projected is not None else result.spent
        projected += whole
        out(f"{name}: ${result.spent:.2f} spent, ${whole:.2f} projected")
        if result.code != 0:
            out(f"stopped in {name}: spent ${spent:.2f} of the ${cap:.2f} cap")
            return 2
    tail = f"; ${projected:.2f} projected for every app" if sample else ""
    out(f"spent ${spent:.2f} of the ${cap:.2f} cap{tail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="record_all", description=__doc__)
    parser.add_argument("--max-usd", type=float, default=0.0, help="the approved cap, in dollars")
    parser.add_argument("--sample", type=int, help="record only the first N cases of each app")
    parser.add_argument("--model-name", default="claude-opus-5-5")
    args = parser.parse_args(argv)

    def live(case_id: str) -> Model:
        from freight_agents.llm.anthropic_adapter import AnthropicModel

        return AnthropicModel(model=args.model_name, effort="low")

    return record_all(apps(), args.max_usd, args.sample, live)


if __name__ == "__main__":
    sys.exit(main())
