import datetime as dt
from pathlib import Path

from freight_agents.carrier_filing.deadlines import (
    ACK_DAYS,
    DISPOSITION_DAYS,
    deadlines,
    reminder_at,
    schedule_deadlines,
)
from freight_agents.carrier_filing.machine import FILING_MACHINE
from freight_agents.statecore.engine import CaseEngine
from freight_agents.statecore.store import SqliteEventStore

from .conftest import Clock

ZONE = "America/Chicago"


def test_deadlines_count_calendar_days_from_receipt() -> None:
    d = deadlines(dt.date(2026, 12, 1))
    assert (ACK_DAYS, DISPOSITION_DAYS) == (30, 120)
    assert d.acknowledgement_due == dt.date(2026, 12, 31)
    assert d.disposition_due == dt.date(2027, 3, 31)
    assert d.status_letters(until=dt.date(2027, 8, 1)) == [dt.date(2027, 5, 30),
                                                         dt.date(2027, 7, 29)]  # fmt: skip


def test_month_ends_and_leap_years() -> None:
    d = deadlines(dt.date(2027, 1, 31))
    assert d.acknowledgement_due == dt.date(2027, 3, 2)
    assert d.disposition_due == dt.date(2027, 5, 31)
    assert deadlines(dt.date(2028, 2, 1)).acknowledgement_due == dt.date(2028, 3, 2)


def test_reminders_fire_at_nine_local_on_the_first_late_day_across_daylight_time() -> None:
    # Central time moves from UTC-6 to UTC-5 on 2027-03-14.
    assert reminder_at(dt.date(2027, 3, 11), ZONE) == dt.datetime(2027, 3, 12, 15, 0,
                                                                  tzinfo=dt.UTC)  # fmt: skip
    assert reminder_at(dt.date(2027, 3, 14), ZONE) == dt.datetime(2027, 3, 15, 14, 0,
                                                                  tzinfo=dt.UTC)  # fmt: skip


def _filed(tmp_path: Path, clock: Clock) -> tuple[CaseEngine, str]:
    engine = CaseEngine(FILING_MACHINE, SqliteEventStore(tmp_path / "events.sqlite3"), clock)
    engine.open("claim-001", {"reference": "claim-001"}, actor="test")
    engine.fire("claim-001", "filed", {"receipt": {"received_on": "2026-12-01"}}, actor="test")
    schedule_deadlines(engine, "claim-001", dt.date(2026, 12, 1), ZONE)
    return engine, "claim-001"


def test_a_due_timer_fires_once(tmp_path: Path, clock: Clock) -> None:
    engine, case = _filed(tmp_path, clock)
    clock.now = dt.datetime(2027, 1, 2, tzinfo=dt.UTC)
    fired = engine.fire_due(clock.now)
    assert [t.event for t in fired] == ["ack_overdue"]
    assert engine.view(case).state == "followup_pending"
    assert engine.fire_due(clock.now) == []


def test_a_timer_does_nothing_once_the_case_has_moved(tmp_path: Path, clock: Clock) -> None:
    engine, case = _filed(tmp_path, clock)
    clock.now = dt.datetime(2026, 12, 30, tzinfo=dt.UTC)  # acknowledged on day 29
    engine.fire(case, "acknowledged", {"acknowledged_on": "2026-12-30"}, actor="carrier")
    clock.now = dt.datetime(2027, 1, 2, tzinfo=dt.UTC)
    assert engine.fire_due(clock.now) == []
    assert engine.view(case).state == "acknowledged"
    clock.now = dt.datetime(2027, 4, 2, tzinfo=dt.UTC)
    assert [t.event for t in engine.fire_due(clock.now)] == ["disposition_overdue"]


def test_a_resolved_claim_skips_every_timer(tmp_path: Path, clock: Clock) -> None:
    engine, case = _filed(tmp_path, clock)
    engine.fire(case, "resolved", {"disposition": "paid"}, actor="carrier")
    clock.now = dt.datetime(2027, 6, 1, tzinfo=dt.UTC)
    assert engine.fire_due(clock.now) == []
    assert engine.view(case).state == "resolved"
