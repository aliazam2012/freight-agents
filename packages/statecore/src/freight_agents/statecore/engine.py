"""Cases: a state machine driven by events, with data and timers.

Every change is an event. The current view of a case is always rebuilt from
its events, so the log is the truth and nothing else can drift from it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .machine import CaseView, IllegalTransition, StateMachine
from .store import SqliteEventStore


class CaseExists(RuntimeError):
    """A case with this id is already open."""


@dataclass(frozen=True)
class Timer:
    case_id: str
    timer_id: str
    event: str
    due_at: datetime
    payload: dict[str, Any]


class CaseEngine:
    def __init__(
        self, machine: StateMachine, store: SqliteEventStore, clock: Callable[[], datetime]
    ) -> None:
        self.machine = machine
        self.store = store
        self.clock = clock

    def exists(self, case_id: str) -> bool:
        return bool(self.store.events(case_id))

    def open(self, case_id: str, data: dict[str, Any], actor: str = "system") -> CaseView:
        if self.exists(case_id):
            raise CaseExists(case_id)
        payload = {"state": self.machine.initial, "data": data}
        self.store.append(case_id, "opened", payload, actor=actor, expected_seq=0, at=self.clock())
        return self.view(case_id)

    def view(self, case_id: str) -> CaseView:
        events = self.store.events(case_id)
        if not events:
            raise KeyError(f"no case {case_id}")
        state, data = self.machine.initial, {}
        for event in events:
            if event.type == "opened":
                state, data = event.payload["state"], dict(event.payload["data"])
            elif event.type == "transition":
                state = event.payload["to"]
                data.update(event.payload.get("data", {}))
            elif event.type == "patched":
                data.update(event.payload["data"])
        return CaseView(case_id, state, data, events[-1].seq, events)

    def fire(
        self,
        case_id: str,
        event: str,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> CaseView:
        case = self.view(case_id)
        body = payload or {}
        target = self.machine.next_state(case, event, body)
        self.store.append(
            case_id,
            "transition",
            {"event": event, "from": case.state, "to": target, "data": body},
            actor=actor,
            expected_seq=case.seq,
            at=self.clock(),
        )
        return self.view(case_id)

    def patch(self, case_id: str, data: dict[str, Any], actor: str) -> CaseView:
        case = self.view(case_id)
        self.store.append(
            case_id, "patched", {"data": data}, actor=actor, expected_seq=case.seq, at=self.clock()
        )
        return self.view(case_id)

    def schedule(
        self, case_id: str, event: str, due_at: datetime, payload: dict[str, Any] | None = None
    ) -> str:
        case = self.view(case_id)
        timer_id = f"tmr_{uuid.uuid4().hex[:10]}"
        self.store.append(
            case_id,
            "timer_scheduled",
            {
                "timer_id": timer_id,
                "event": event,
                "due_at": due_at.isoformat(),
                "payload": payload or {},
            },
            actor="system",
            expected_seq=case.seq,
            at=self.clock(),
        )
        return timer_id

    def due(self, now: datetime) -> list[Timer]:
        found: list[Timer] = []
        for case_id in self.store.case_ids():
            scheduled: dict[str, Timer] = {}
            for event in self.store.events(case_id):
                if event.type == "timer_scheduled":
                    p = event.payload
                    scheduled[p["timer_id"]] = Timer(
                        case_id,
                        p["timer_id"],
                        p["event"],
                        datetime.fromisoformat(p["due_at"]),
                        p["payload"],
                    )
                elif event.type in ("timer_fired", "timer_skipped"):
                    scheduled.pop(event.payload["timer_id"], None)
            found.extend(t for t in scheduled.values() if t.due_at <= now)
        return sorted(found, key=lambda t: t.due_at)

    def fire_due(self, now: datetime, actor: str = "timer") -> list[Timer]:
        """Fire every due timer once; a timer whose case moved on is skipped, not retried."""
        fired: list[Timer] = []
        for timer in self.due(now):
            try:
                self.fire(timer.case_id, timer.event, timer.payload, actor=actor)
            except IllegalTransition as exc:
                self._close_timer(timer, "timer_skipped", reason=exc.reason)
                continue
            self._close_timer(timer, "timer_fired")
            fired.append(timer)
        return fired

    def _close_timer(self, timer: Timer, kind: str, reason: str | None = None) -> None:
        case = self.view(timer.case_id)
        payload: dict[str, Any] = {"timer_id": timer.timer_id}
        if reason:
            payload["reason"] = reason
        self.store.append(
            timer.case_id, kind, payload, actor="timer", expected_seq=case.seq, at=self.clock()
        )
