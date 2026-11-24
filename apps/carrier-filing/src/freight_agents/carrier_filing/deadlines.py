"""The carrier's deadlines under 49 CFR 370, counted in calendar days from receipt.

370.5(a): acknowledge a claim in writing within 30 days of receiving it (unless paid or
declined in that time). 370.9(a): pay, decline or make a firm compromise offer within
120 days; 370.9(b): if it cannot, write to the claimant then and every 60 days after
with the status and the reason for the delay. Sourced text: the knowledge package,
docs/49-cfr-370.md.

Days are counted on dates, never on clock time, so month ends and daylight-saving
changes cannot move a deadline. A reminder fires at 09:00 claimant local time on the
first day after a deadline passes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from freight_agents.statecore.engine import CaseEngine

ACK_DAYS = 30
DISPOSITION_DAYS = 120
STATUS_EVERY_DAYS = 60
REMINDER_HOUR = 9


@dataclass(frozen=True)
class Deadlines:
    received_on: dt.date

    @property
    def acknowledgement_due(self) -> dt.date:
        return self.received_on + dt.timedelta(days=ACK_DAYS)

    @property
    def disposition_due(self) -> dt.date:
        return self.received_on + dt.timedelta(days=DISPOSITION_DAYS)

    def status_letters(self, until: dt.date) -> list[dt.date]:
        out, day = [], self.disposition_due + dt.timedelta(days=STATUS_EVERY_DAYS)
        while day <= until:
            out.append(day)
            day += dt.timedelta(days=STATUS_EVERY_DAYS)
        return out


def deadlines(received_on: dt.date) -> Deadlines:
    return Deadlines(received_on)


def reminder_at(due: dt.date, zone: str) -> dt.datetime:
    """09:00 local on the day after `due`, in UTC."""
    local = dt.datetime.combine(
        due + dt.timedelta(days=1), dt.time(REMINDER_HOUR), tzinfo=ZoneInfo(zone)
    )
    return local.astimezone(dt.UTC)


def schedule_deadlines(engine: CaseEngine, case_id: str, received_on: dt.date, zone: str) -> None:
    """At filing: one reminder for the 370.5 acknowledgement, one for the 370.9 disposition."""
    d = deadlines(received_on)
    engine.schedule(
        case_id,
        "ack_overdue",
        reminder_at(d.acknowledgement_due, zone),
        {"rule": "49 CFR 370.5", "due": d.acknowledgement_due.isoformat()},
    )
    engine.schedule(
        case_id,
        "disposition_overdue",
        reminder_at(d.disposition_due, zone),
        {"rule": "49 CFR 370.9", "due": d.disposition_due.isoformat()},
    )


def schedule_status(engine: CaseEngine, case_id: str, last: dt.date, zone: str) -> None:
    """After a disposition follow-up: the next 370.9(b) status reminder, 60 days on."""
    due = last + dt.timedelta(days=STATUS_EVERY_DAYS)
    engine.schedule(
        case_id,
        "status_overdue",
        reminder_at(due, zone),
        {"rule": "49 CFR 370.9(b)", "due": due.isoformat()},
    )
