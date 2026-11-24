"""Orders and tenders.

The types are deliberately loose about formats (a ZIP code is a string, a hazmat
UN number may be missing): a tender that breaks a rule must still be represented,
so `validate.py` can say which rule and why, instead of a parser raising.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel


class Equipment(StrEnum):
    DRY_VAN_53 = "dry_van_53"
    DRY_VAN_48 = "dry_van_48"
    REEFER_53 = "reefer_53"


class StopKind(StrEnum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


class Source(StrEnum):
    EDI = "edi"
    PDF = "pdf"
    EMAIL = "email"


class Purpose(StrEnum):
    ORIGINAL = "original"
    CHANGE = "change"
    CANCEL = "cancel"


class Party(BaseModel):
    name: str
    street: str
    city: str
    state: str
    zip: str


class Stop(BaseModel):
    sequence: int
    kind: StopKind
    party: Party
    window_start: dt.datetime  # local time at the stop
    window_end: dt.datetime
    time_zone: str | None  # IANA name, from the place table when the tender does not say
    reference: str | None


class Hazmat(BaseModel):
    un_number: str | None
    proper_shipping_name: str | None
    hazard_class: str | None
    packing_group: str | None
    emergency_phone: str | None


class Order(BaseModel):
    tender_id: str
    scac: str
    shipper: Party
    shipper_reference: str
    stops: list[Stop]
    equipment: Equipment
    weight_lb: int
    pieces: int
    commodity: str
    reefer_setpoint_f: int | None
    hazmat: Hazmat | None
    rate_usd: float | None


class Tender(BaseModel):
    source: Source
    purpose: Purpose
    order: Order
    reference: str  # interchange control number, file name or message id
    received_at: dt.datetime  # UTC
