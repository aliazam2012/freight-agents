"""Validation rules for an order. Each finding names its rule, its weight and its source.

Severities: ``block`` stops the order from reaching the TMS; ``review`` sends it to a
person; ``notice`` is information that travels with the order (placards required).
Times are compared in UTC from each stop's own time zone, because a window is
written in local time at the stop and two stops can be zones apart.

Sources, read 2026-11-23, summarized in the knowledge package (docs/orders):
USPS Publication 28 appendix B (state codes; a Five-Digit ZIP Code or a ZIP+4 Code of
10 positions); C.H. Robinson's equipment guide (payloads, which keep a loaded truck
within the 80,000-pound gross limit of 23 U.S.C. 127); 49 CFR 172.202 (shipping
description), 172.504 (placards) and 172.604 (emergency phone); the CN and C.H.
Robinson 204 guides (stop sequence, lading quantity, temperature control).
"""

from __future__ import annotations

import datetime as dt
import itertools
import re
from typing import Literal
from zoneinfo import ZoneInfo

from freight_agents.tms_orders.domain import Equipment, Order, Party, Stop, StopKind
from freight_agents.tms_orders.limits import PAYLOAD_LB
from freight_agents.tms_orders.places import transit_days, zone_place
from pydantic import BaseModel

USPS = "https://pe.usps.com/text/pub28/28apb.htm"
PAYLOADS = (
    "https://www.chrobinson.com/en-US/-/media/ChRobinson/documents/"
    "Truckload%20Equipment%20Guide.pdf"
)
CFR_202 = "https://www.law.cornell.edu/cfr/text/49/172.202"
CFR_504 = "https://www.law.cornell.edu/cfr/text/49/172.504"
CFR_604 = "https://www.law.cornell.edu/cfr/text/49/172.604"
CN_204 = (
    "https://www.cn.ca/-/media/files/customer-centre/"
    "customer-centre-documents/204-implementation-guide-4010.pdf"
)
CHR_204 = (
    "https://www.chrobinson.com/en-CA/-/media/ChRobinson/documents/"
    "carrier-specs-docs/international-dray-carrier-specs/204%20International%20Dray%20Carrier%20Specs.pdf?la=en-CA"
)
PLANNING = (
    "Planning assumption: stop times are local to the stop, "
    "one driver covers about 500 road miles a day"
)

STATES = frozenset(
    [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    ]
)
# Anchored, no nested quantifiers.
ZIP = re.compile(r"\d{5}(?:-\d{4})?")
UN_NUMBER = re.compile(r"(?:UN|NA)\d{4}")
CLASSES = frozenset(
    [
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "2.1",
        "2.2",
        "2.3",
        "3",
        "4.1",
        "4.2",
        "4.3",
        "5.1",
        "5.2",
        "6.1",
        "6.2",
        "7",
        "8",
        "9",
    ]
)
# Classes whose materials always carry a packing group in the 172.101 table.
NEEDS_PACKING_GROUP = frozenset(["3", "4.1", "4.2", "4.3", "5.1", "6.1", "8"])
PACKING_GROUPS = frozenset({"I", "II", "III"})
# 172.504 table 1, by class alone. Divisions 5.2, 6.1 and class 7 are table 1 only for
# particular materials or labels the order does not carry, so they count as table 2 here.
TABLE_1 = frozenset({"1.1", "1.2", "1.3", "2.3", "4.3"})
PLACARD_FROM_LB = 1_001

Severity = Literal["block", "review", "notice"]


class Finding(BaseModel):
    rule: str
    severity: Severity
    message: str
    source: str


def _utc(moment: dt.datetime, zone: str | None) -> dt.datetime:
    if zone is None:
        return moment.replace(tzinfo=dt.UTC)
    return moment.replace(tzinfo=ZoneInfo(zone)).astimezone(dt.UTC)


def _start(stop: Stop) -> dt.datetime:
    return _utc(stop.window_start, stop.time_zone)


def _end(stop: Stop) -> dt.datetime:
    return _utc(stop.window_end, stop.time_zone)


def _address(where: str, party: Party) -> list[Finding]:
    out = []
    if party.state not in STATES:
        out.append(Finding(rule="address.state", severity="block",
                           message=f"{where}: {party.state!r} is not a USPS state code",
                           source=USPS))  # fmt: skip
    if not ZIP.fullmatch(party.zip):
        out.append(Finding(rule="address.zip", severity="block",
                           message=f"{where}: {party.zip!r} is not a ZIP Code or ZIP+4 Code",
                           source=USPS))  # fmt: skip
    return out


def _stops(order: Order, now: dt.datetime) -> list[Finding]:
    out: list[Finding] = []
    stops = order.stops
    if (
        [s.sequence for s in stops] != list(range(1, len(stops) + 1))
        or not stops
        or stops[0].kind != StopKind.PICKUP
        or all(s.kind != StopKind.DELIVERY for s in stops)
    ):
        out.append(Finding(rule="stops.sequence", severity="block",
                           message="stops must count up from 1, start with a pickup and "
                           "include a delivery", source=CN_204))  # fmt: skip
    for s in stops:
        if s.time_zone is None:
            out.append(Finding(rule="address.time_zone", severity="review",
                               message=f"stop {s.sequence}: no time zone known for "
                               f"{s.party.city}, {s.party.state}", source=PLANNING))  # fmt: skip
        if _end(s) <= _start(s):
            out.append(Finding(rule="window.order", severity="block",
                               message=f"stop {s.sequence}: the window ends before it starts",
                               source=CHR_204))  # fmt: skip
    pickups = [s for s in stops if s.kind == StopKind.PICKUP]
    deliveries = [s for s in stops if s.kind == StopKind.DELIVERY]
    if pickups and deliveries:
        loaded = max(_start(s) for s in pickups)
        early = [d for d in deliveries if _end(d) < loaded]
        if early:
            out.append(Finding(rule="window.delivery_before_pickup", severity="block",
                               message=f"stop {early[0].sequence}: the delivery window closes "
                               "before the pickup window opens", source=CHR_204))  # fmt: skip
    for before, after in itertools.pairwise(stops):
        if _start(after) < _start(before):
            continue  # already a sequence or window finding
        try:
            need = transit_days(zone_place(before.party), zone_place(after.party))
        except KeyError:
            continue
        if (after.window_start.date() - before.window_start.date()).days < need:
            out.append(Finding(rule="window.transit", severity="review",
                               message=f"stop {after.sequence}: {need} days of driving from "
                               f"stop {before.sequence} do not fit", source=PLANNING))  # fmt: skip
    if pickups and _end(pickups[0]) < now:
        out.append(
            Finding(
                rule="window.past",
                severity="review",
                message="the pickup window has already closed",
                source=PLANNING,
            )
        )
    return out


def _load(order: Order) -> list[Finding]:
    out: list[Finding] = []
    if order.pieces <= 0 or order.weight_lb <= 0:
        out.append(Finding(rule="load.pieces", severity="block",
                           message="weight and piece count must be positive",
                           source=CN_204))  # fmt: skip
    limit = PAYLOAD_LB[order.equipment]
    if order.weight_lb > limit:
        out.append(Finding(rule="weight.payload", severity="block",
                           message=f"{order.weight_lb:,} lb is over the {limit:,} lb payload of "
                           f"a {order.equipment.value}", source=PAYLOADS))  # fmt: skip
    reefer = order.equipment == Equipment.REEFER_53
    if reefer and order.reefer_setpoint_f is None:
        out.append(Finding(rule="reefer.setpoint", severity="block",
                           message="a reefer load needs a temperature setpoint",
                           source=CHR_204))  # fmt: skip
    if not reefer and order.reefer_setpoint_f is not None:
        out.append(Finding(rule="reefer.setpoint_on_dry_van", severity="review",
                           message="a temperature setpoint on a dry van: check the equipment",
                           source=CHR_204))  # fmt: skip
    return out


def _hazmat(order: Order) -> list[Finding]:
    h = order.hazmat
    if h is None:
        return []

    def block(rule: str, message: str, source: str = CFR_202) -> Finding:
        return Finding(rule=rule, severity="block", message=message, source=source)

    out = []
    if not h.un_number or not UN_NUMBER.fullmatch(h.un_number):
        out.append(block("hazmat.un_number", "the identification number must read UN or NA "
                         "and four digits"))  # fmt: skip
    if not h.proper_shipping_name:
        out.append(block("hazmat.shipping_name", "the proper shipping name is missing"))
    if h.hazard_class not in CLASSES:
        out.append(block("hazmat.class", f"{h.hazard_class!r} is not a hazard class or division",
                         CFR_504))  # fmt: skip
    if h.packing_group is not None and h.packing_group not in PACKING_GROUPS:
        out.append(block("hazmat.packing_group", f"{h.packing_group!r} is not I, II or III"))
    elif h.packing_group is None and h.hazard_class in NEEDS_PACKING_GROUP:
        out.append(block("hazmat.packing_group", f"class {h.hazard_class} needs a packing group"))
    digits = sum(c.isdigit() for c in h.emergency_phone or "")
    if digits < 10:
        out.append(block("hazmat.emergency_phone", "a monitored emergency response number with "
                         "its area code is required", CFR_604))  # fmt: skip
    if h.hazard_class in TABLE_1 or (
        h.hazard_class in CLASSES and order.weight_lb >= PLACARD_FROM_LB
    ):
        out.append(Finding(rule="hazmat.placards", severity="notice",
                           message=f"placards required for class {h.hazard_class} at "
                           f"{order.weight_lb:,} lb", source=CFR_504))  # fmt: skip
    return out


def validate_order(order: Order, now: dt.datetime) -> list[Finding]:
    findings = _address("shipper", order.shipper)
    for stop in order.stops:
        findings += _address(f"stop {stop.sequence}", stop.party)
    return findings + _stops(order, now) + _load(order) + _hazmat(order)
