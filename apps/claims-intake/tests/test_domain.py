from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from freight_agents.claims_intake.domain import (
    ClaimFields,
    add_months,
    filing_deadline,
    filing_window,
    missing_requirements,
)
from freight_agents.claims_intake.machine import CLAIMS_MACHINE
from freight_agents.statecore.engine import CaseEngine
from freight_agents.statecore.machine import IllegalTransition
from freight_agents.statecore.store import SqliteEventStore

COMPLETE: dict[str, Any] = {
    "pro_number": "7741-2209",
    "bol_number": None,
    "carrier": "Example Freight Lines",
    "ship_date": date(2026, 11, 2),
    "delivery_date": date(2026, 11, 9),
    "commodity": "dining chairs",
    "claim_type": "damage",
    "damage_description": "4 of 12 chairs arrived with broken legs",
    "claimed_amount_usd": 800.0,
    "claimant_name": "Dana Reyes",
    "claimant_email": "dana@example.com",
    "photo_count": 3,
}


def test_add_months_clamps_to_the_end_of_the_month() -> None:
    assert add_months(date(2026, 5, 31), 9) == date(2027, 2, 28)
    assert add_months(date(2026, 1, 10), 9) == date(2026, 10, 10)


def test_filing_deadline_is_the_nine_month_floor() -> None:
    assert filing_deadline(date(2026, 1, 10)) == date(2026, 10, 10)


@pytest.mark.parametrize(
    ("received", "expected"),
    [(date(2026, 3, 1), "open"), (date(2026, 9, 20), "closing"), (date(2026, 10, 11), "late")],
)
def test_filing_window(received: date, expected: str) -> None:
    assert filing_window(date(2026, 1, 10), received) == expected


def test_no_delivery_date_means_unknown_and_asks_for_it() -> None:
    fields = ClaimFields(**{**COMPLETE, "delivery_date": None})
    assert filing_window(None, date(2026, 11, 22)) == "unknown"
    assert missing_requirements(fields) == ["delivery_date"]


def test_a_complete_claim_misses_nothing() -> None:
    assert missing_requirements(ClaimFields(**COMPLETE)) == []


def test_each_370_3_requirement_is_named() -> None:
    bare = ClaimFields(**{k: None for k in COMPLETE})
    assert missing_requirements(bare) == ["shipment_id", "liability", "amount", "delivery_date"]
    zero = ClaimFields(**{**COMPLETE, "claimed_amount_usd": 0.0})
    assert missing_requirements(zero) == ["amount"]
    by_bol = ClaimFields(**{**COMPLETE, "pro_number": None, "bol_number": "BOL-55102"})
    assert missing_requirements(by_bol) == []


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 22, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _engine(tmp_path: Path) -> CaseEngine:
    return CaseEngine(CLAIMS_MACHINE, SqliteEventStore(tmp_path / "e.sqlite3"), Clock())


def test_complete_is_refused_while_something_is_missing(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.open("c1", {})
    engine.fire("c1", "triage_claim")
    partial = ClaimFields(**{**COMPLETE, "claimed_amount_usd": None}).model_dump(mode="json")
    engine.fire("c1", "extracted", {"fields": partial})
    with pytest.raises(IllegalTransition, match="amount"):
        engine.fire("c1", "complete")
    assert engine.fire("c1", "incomplete").state == "needs_info"


def test_an_overdue_reply_returns_the_case_to_needs_info(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    clock = engine.clock
    assert isinstance(clock, Clock)
    engine.open("c1", {})
    engine.fire("c1", "triage_claim")
    engine.fire("c1", "extracted", {"fields": {k: None for k in COMPLETE}})
    engine.fire("c1", "incomplete")
    engine.fire("c1", "request_sent")
    engine.schedule("c1", "reply_overdue", due_at=clock.now + timedelta(days=7))
    clock.now += timedelta(days=7)
    engine.fire_due(clock.now)
    assert engine.view("c1").state == "needs_info"
