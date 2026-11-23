"""Claim rules, from 49 CFR 370.3 and 49 U.S.C. 14706(e).

The filing deadline here is the statutory floor: 9 months, measured from
delivery as bills of lading commonly do. A bill of lading may allow longer,
so "late" means "past the floor, check the contract", not "rejected".
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

FILING_FLOOR_MONTHS = 9
CLOSING_DAYS = 30

Window = Literal["open", "closing", "late", "unknown"]


class ClaimFields(BaseModel):
    """What the extraction step pulls from a claim email. Unknown means None."""

    model_config = ConfigDict(extra="forbid")

    pro_number: str | None
    bol_number: str | None
    carrier: str | None
    ship_date: date | None
    delivery_date: date | None
    commodity: str | None
    claim_type: Literal["damage", "shortage", "loss"] | None
    damage_description: str | None
    claimed_amount_usd: float | None
    claimant_name: str | None
    claimant_email: str | None
    photo_count: int | None


def add_months(day: date, months: int) -> date:
    years, month_index = divmod(day.month - 1 + months, 12)
    year, month = day.year + years, month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def filing_deadline(delivery_date: date) -> date:
    return add_months(delivery_date, FILING_FLOOR_MONTHS)


def filing_window(delivery_date: date | None, received_on: date) -> Window:
    if delivery_date is None:
        return "unknown"
    deadline = filing_deadline(delivery_date)
    if received_on > deadline:
        return "late"
    if (deadline - received_on).days <= CLOSING_DAYS:
        return "closing"
    return "open"


def missing_requirements(fields: ClaimFields) -> list[str]:
    """The 370.3(b) minimums, plus the delivery date this app needs for the window."""
    missing = []
    if not (fields.pro_number or fields.bol_number):
        missing.append("shipment_id")
    if not (fields.claim_type and fields.damage_description):
        missing.append("liability")
    if not (fields.claimed_amount_usd and fields.claimed_amount_usd > 0):
        missing.append("amount")
    if fields.delivery_date is None:
        missing.append("delivery_date")
    return missing
