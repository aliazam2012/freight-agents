"""State machines: named states, named events, guarded transitions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .store import Event


@dataclass(frozen=True)
class CaseView:
    case_id: str
    state: str
    data: dict[str, Any]
    seq: int
    history: list[Event] = field(default_factory=list)


# A guard returns None to allow the move, or the reason it refuses.
Guard = Callable[[CaseView, dict[str, Any]], str | None]


@dataclass(frozen=True)
class Transition:
    source: str
    event: str
    target: str
    guard: Guard | None = None


class IllegalTransition(Exception):
    def __init__(self, state: str, event: str, reason: str) -> None:
        super().__init__(f"cannot {event} from {state}: {reason}")
        self.state = state
        self.event = event
        self.reason = reason


class StateMachine:
    def __init__(
        self,
        name: str,
        initial: str,
        transitions: Iterable[Transition],
        terminal: Iterable[str] = (),
    ) -> None:
        self.name = name
        self.initial = initial
        self.terminal = frozenset(terminal)
        self._moves: dict[tuple[str, str], Transition] = {}
        for t in transitions:
            key = (t.source, t.event)
            if key in self._moves:
                raise ValueError(f"{name}: two transitions for {t.event} from {t.source}")
            self._moves[key] = t
        self.states = frozenset(
            {initial, *self.terminal}
            | {t.source for t in self._moves.values()}
            | {t.target for t in self._moves.values()}
        )

    def events_from(self, state: str) -> list[str]:
        return [event for (source, event) in self._moves if source == state]

    def next_state(self, case: CaseView, event: str, payload: dict[str, Any]) -> str:
        if case.state in self.terminal:
            raise IllegalTransition(case.state, event, f"{case.state} is terminal")
        move = self._moves.get((case.state, event))
        if move is None:
            allowed = ", ".join(self.events_from(case.state)) or "nothing"
            raise IllegalTransition(case.state, event, f"allowed here: {allowed}")
        if move.guard is not None:
            refusal = move.guard(case, payload)
            if refusal:
                raise IllegalTransition(case.state, event, refusal)
        return move.target
