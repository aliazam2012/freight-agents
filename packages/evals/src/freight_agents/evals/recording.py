"""Record a real model's turns for an evaluation, one cassette per case, under a cap.

Each case runs on the live model wrapped twice: a meter that prices every turn, and a
recorder that writes the turns to `<case>.jsonl.part`, renamed to `<case>.jsonl` only
when the case finishes. So a crash or a failed case leaves no cassette, and a later run
records only the cases still missing: what was recorded is never paid for twice.

Spending is held under the cap before each case, not after: a case starts only if what
was spent plus the most any case has cost so far stays within the cap. A model with no
known price is refused, since its cost could not be held to anything.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from freight_agents.llm import (
    CassetteMiss,
    Message,
    Model,
    ModelTurn,
    RecordingModel,
    ReplayModel,
    ToolSpec,
)
from freight_agents.llm.costs import Price, cost_usd


class Unpriced(RuntimeError):
    """The model's turns have no known price."""


class MeteredModel:
    """Prices every turn the inner model returns; refuses a turn it cannot price."""

    def __init__(self, inner: Model, prices: Mapping[str, Price] | None = None) -> None:
        self._inner, self._prices = inner, prices
        self.spent = 0.0
        self.tokens = 0

    @property
    def name(self) -> str:
        return self._inner.name

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        turn = self._inner.complete(system, messages, tools)
        cost = cost_usd(turn.model, turn.usage, self._prices)
        if cost is None:
            raise Unpriced(f"{turn.model} has no known price")
        self.spent += cost
        self.tokens += turn.usage.input_tokens + turn.usage.output_tokens
        return turn


def cassette_cost(path: Path, prices: Mapping[str, Price] | None = None) -> float:
    """What a recorded case cost, priced from the usage its turns carry."""
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            turn = ModelTurn.model_validate(json.loads(line)["turn"])
            total += cost_usd(turn.model, turn.usage, prices) or 0.0
    return total


@dataclass
class RecordResult:
    code: int
    spent: float = 0.0  # in this run
    prior: float = 0.0  # what the cassettes already on disk cost when they were recorded
    recorded: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    projected: float | None = None


def record_cases(
    case_ids: Sequence[str],
    run_one: Callable[[str, Model], object],
    live: Callable[[str], Model],
    cassettes: Path,
    cap: float,
    total: int | None = None,
    prices: Mapping[str, Price] | None = None,
    out: Callable[[str], object] = print,
) -> RecordResult:
    """Record each case's live turns; stop before a case that could pass the cap."""
    result = RecordResult(code=0)
    if cap <= 0:
        out("recording spends money: pass --max-usd with the approved cap")
        result.code = 2
        return result
    cassettes.mkdir(parents=True, exist_ok=True)
    largest = 0.0
    for case_id in case_ids:
        final = cassettes / f"{case_id}.jsonl"
        if final.exists():
            # Already paid for: it counts toward the cap and informs the next estimate.
            cost = cassette_cost(final, prices)
            result.prior += cost
            largest = max(largest, cost)
            result.kept.append(case_id)
            continue
        if result.prior + result.spent + largest > cap:
            out(f"stopped before {case_id}: it could pass the ${cap:.2f} spending cap")
            result.code = 2
            return result
        part = cassettes / f"{case_id}.jsonl.part"
        part.unlink(missing_ok=True)
        meter = MeteredModel(live(case_id), prices)
        try:
            run_one(case_id, RecordingModel(meter, part))
        except Unpriced as exc:
            part.unlink(missing_ok=True)
            out(f"{case_id}: {exc}; refusing to record with no known price")
            result.code = 2
            return result
        except Exception as exc:
            part.unlink(missing_ok=True)
            result.spent += meter.spent
            out(f"{case_id}: {type(exc).__name__}: {exc}; nothing kept for this case")
            result.code = 2
            return result
        part.touch()  # a case that never called the model keeps an empty cassette
        part.replace(final)
        result.spent += meter.spent
        largest = max(largest, meter.spent)
        result.recorded.append(case_id)
        out(
            f"{case_id:<28} {meter.tokens:>8} tokens  ${meter.spent:.4f}  total ${result.spent:.4f}"
        )
    done = len(result.recorded) + len(result.kept)
    if total is not None and done and total > done:
        result.projected = (result.prior + result.spent) / done * total
        out(f"${result.projected:.2f} projected for all {total} cases (from {done} recorded)")
    return result


class StaleCassette(RuntimeError):
    """A case's cassette is missing or no longer matches what the model is asked."""


class _NamedReplay:
    """A cassette replay whose misses name the case they belong to."""

    def __init__(self, case_id: str, inner: ReplayModel) -> None:
        self._case_id, self._inner = case_id, inner

    @property
    def name(self) -> str:
        return self._inner.name

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        try:
            return self._inner.complete(system, messages, tools)
        except CassetteMiss as exc:
            raise StaleCassette(
                f"{self._case_id}: {exc}; the prompt or tools changed since it was recorded: "
                "re-record this case"
            ) from exc


def replay_model(case_id: str, cassettes: Path, model_name: str) -> Model:
    """The recorded turns of one case; a missing or stale cassette names the case."""
    path = cassettes / f"{case_id}.jsonl"
    if not path.exists():
        raise StaleCassette(f"{case_id}: no cassette; record it first")
    return _NamedReplay(case_id, ReplayModel(path, name=model_name))


def replay[T](
    case_id: str, cassettes: Path, model_name: str, run_one: Callable[[str, Model], T]
) -> T:
    """Run one case on its recorded turns."""
    return run_one(case_id, replay_model(case_id, cassettes, model_name))
