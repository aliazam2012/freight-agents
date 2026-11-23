import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from freight_agents.statecore.engine import CaseEngine
from freight_agents.statecore.machine import CaseView, IllegalTransition, StateMachine, Transition
from freight_agents.statecore.store import ConcurrencyError, SqliteEventStore

START = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


def has_amount(case: CaseView, payload: dict[str, Any]) -> str | None:
    return None if case.data.get("amount") else "no amount on the case"


MACHINE = StateMachine(
    name="demo",
    initial="new",
    transitions=[
        Transition("new", "review", "reviewing"),
        Transition("reviewing", "approve", "approved", guard=has_amount),
        Transition("reviewing", "chase", "waiting"),
        Transition("waiting", "nudge", "reviewing"),
        Transition("approved", "close", "closed"),
    ],
    terminal={"closed"},
)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def engine(tmp_path: Path) -> CaseEngine:
    return CaseEngine(MACHINE, SqliteEventStore(tmp_path / "events.sqlite3"), Clock())


def test_legal_transitions_move_the_case(engine: CaseEngine) -> None:
    engine.open("c1", {"amount": 120})
    assert engine.fire("c1", "review", actor="agent").state == "reviewing"
    assert engine.fire("c1", "approve", actor="agent").state == "approved"


def test_an_illegal_event_names_the_state_and_event(engine: CaseEngine) -> None:
    engine.open("c1", {})
    with pytest.raises(IllegalTransition) as err:
        engine.fire("c1", "approve", actor="agent")
    assert (err.value.state, err.value.event) == ("new", "approve")


def test_a_guard_reason_is_carried(engine: CaseEngine) -> None:
    engine.open("c1", {})
    engine.fire("c1", "review", actor="agent")
    with pytest.raises(IllegalTransition, match="no amount on the case"):
        engine.fire("c1", "approve", actor="agent")
    engine.patch("c1", {"amount": 50}, actor="agent")
    assert engine.fire("c1", "approve", actor="agent").state == "approved"


def test_terminal_states_accept_nothing(engine: CaseEngine) -> None:
    engine.open("c1", {"amount": 1})
    for event in ("review", "approve", "close"):
        engine.fire("c1", event, actor="agent")
    with pytest.raises(IllegalTransition, match="terminal"):
        engine.fire("c1", "review", actor="agent")


def test_the_view_is_rebuilt_from_events(engine: CaseEngine, tmp_path: Path) -> None:
    engine.open("c1", {"amount": 1, "note": "a"})
    engine.fire("c1", "review", actor="agent")
    engine.patch("c1", {"note": "b"}, actor="person")
    live = engine.view("c1")
    rebuilt = CaseEngine(MACHINE, SqliteEventStore(tmp_path / "events.sqlite3"), Clock()).view("c1")
    assert rebuilt == live
    assert (rebuilt.state, rebuilt.data, rebuilt.seq) == (
        "reviewing",
        {"amount": 1, "note": "b"},
        3,
    )
    assert [e.type for e in rebuilt.history] == ["opened", "transition", "patched"]


def test_events_cannot_be_changed_or_deleted(engine: CaseEngine, tmp_path: Path) -> None:
    engine.open("c1", {})
    db = sqlite3.connect(tmp_path / "events.sqlite3")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("update events set type = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("delete from events")


def test_a_stale_writer_is_refused(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "events.sqlite3")
    store.append("c1", "opened", {}, actor="a", expected_seq=0, at=START)
    with pytest.raises(ConcurrencyError):
        store.append("c1", "patched", {}, actor="b", expected_seq=0, at=START)


def test_a_timer_fires_once_when_due(engine: CaseEngine) -> None:
    clock = engine.clock
    assert isinstance(clock, Clock)
    engine.open("c1", {})
    engine.fire("c1", "review", actor="agent")
    engine.fire("c1", "chase", actor="agent")
    engine.schedule("c1", "nudge", due_at=START + timedelta(days=7))
    assert engine.due(START + timedelta(days=6)) == []
    clock.now = START + timedelta(days=7)
    fired = engine.fire_due(clock.now)
    assert [t.event for t in fired] == ["nudge"]
    assert engine.view("c1").state == "reviewing"
    assert engine.fire_due(clock.now + timedelta(days=1)) == []


def test_a_timer_for_a_case_that_moved_on_is_skipped(engine: CaseEngine) -> None:
    engine.open("c1", {"amount": 1})
    engine.fire("c1", "review", actor="agent")
    engine.schedule("c1", "nudge", due_at=START)
    fired = engine.fire_due(START + timedelta(minutes=1))
    assert fired == []
    assert engine.view("c1").history[-1].type == "timer_skipped"
