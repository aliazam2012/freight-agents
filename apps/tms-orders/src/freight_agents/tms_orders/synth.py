"""Seeded load tenders for the made-up network: the gold orders every fixture is written from.

Twelve tenders per input type (EDI, PDF, email): seven valid originals, a resend of
one of them under a new reference, a change, a cancellation, an overweight load, and
one that breaks a hazmat or appointment-window rule. Names are invented and checked
in docs/NAMES.md; phone numbers use the 555 exchange; email addresses use example.com.
"""

from __future__ import annotations

import datetime as dt
import itertools
import random
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from freight_agents.tms_orders.domain import (
    Equipment,
    Hazmat,
    Order,
    Party,
    Purpose,
    Source,
    Stop,
    StopKind,
    Tender,
)
from freight_agents.tms_orders.limits import PAYLOAD_LB
from freight_agents.tms_orders.places import PLACES, Place, transit_days

__all__ = ["PAYLOAD_LB", "Case", "email_subject", "generate", "render_email"]

SCAC = "EXFL"  # Example Freight Lines
FIRST_PICKUP = dt.date(2026, 11, 30)
STREETS = ["Industrial Pkwy", "Commerce Dr", "Distribution Way", "Freight Ave", "Logistics Blvd"]


@dataclass(frozen=True)
class Shipper:
    name: str
    prefix: str
    home: str  # place code of its warehouse
    commodities: tuple[str, ...]
    reefer: bool
    hazmat: tuple[tuple[str, str, str, str], ...]  # UN number, name, class, packing group


SHIPPERS = [
    Shipper(
        "Larkspur Home Goods",
        "LHG",
        "MEM",
        ("upholstered furniture", "boxed home goods", "ceramic lamps"),
        reefer=False,
        hazmat=(("UN1263", "Paint", "3", "II"),),
    ),
    Shipper(
        "Brightwater Beverage Works",
        "BBW",
        "DEN",
        ("bottled sparkling water", "canned juice", "cold brew coffee"),
        reefer=True,
        hazmat=(("UN1760", "Corrosive liquid, n.o.s.", "8", "II"),),
    ),
]
CONSIGNEES = ["Harbor Street Furniture", "Northgate Grocery Depot", "Cedar Row Hardware"]
# The last tender in each source breaks one rule; which one rotates across sources.
LAST_RULE = {Source.EDI: "bad_window", Source.PDF: "hazmat_incomplete", Source.EMAIL: "bad_window"}
EXPECTED_RULES = {
    "overweight": ["weight.payload"],
    "bad_window": ["window.delivery_before_pickup"],
    "hazmat_incomplete": ["hazmat.un_number"],
}


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    style: int  # which email style or PDF layout renders it
    tender: Tender
    duplicate_of: str | None
    expected_rules: tuple[str, ...]


def _place(code: str) -> Place:
    return next(p for p in PLACES if p.code == code)


def _party(rng: random.Random, name: str, place: Place) -> Party:
    street = f"{rng.randint(100, 9800)} {rng.choice(STREETS)}"
    return Party(name=name, street=street, city=place.city, state=place.state, zip=place.zip)


def _window(day: dt.date, start_hour: int, hours: int) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time(start_hour))
    return start, start + dt.timedelta(hours=hours)


def _order(rng: random.Random, number: int, hazmat: bool) -> Order:
    shipper = rng.choice(SHIPPERS)
    home = _place(shipper.home)
    stops_out = rng.sample([p for p in PLACES if p.code != shipper.home], rng.choice([1, 1, 2]))
    pickup_day = FIRST_PICKUP + dt.timedelta(days=rng.randint(0, 18))
    start, end = _window(pickup_day, rng.randint(6, 10), 4)
    stops = [
        Stop(
            sequence=1,
            kind=StopKind.PICKUP,
            party=_party(rng, f"{shipper.name} warehouse", home),
            window_start=start,
            window_end=end,
            time_zone=home.time_zone,
            reference=f"PU{rng.randint(100000, 999999)}",
        )
    ]
    day, previous = pickup_day, home
    for seq, place in enumerate(stops_out, start=2):
        day = day + dt.timedelta(days=transit_days(previous, place) + rng.randint(0, 1))
        previous = place
        start, end = _window(day, rng.randint(7, 13), 4)
        stops.append(
            Stop(
                sequence=seq,
                kind=StopKind.DELIVERY,
                party=_party(rng, rng.choice(CONSIGNEES), place),
                window_start=start,
                window_end=end,
                time_zone=place.time_zone,
                reference=f"DL{rng.randint(100000, 999999)}",
            )
        )
    equipment = (
        Equipment.REEFER_53
        if shipper.reefer and rng.random() < 0.5
        else (rng.choice([Equipment.DRY_VAN_53, Equipment.DRY_VAN_53, Equipment.DRY_VAN_48]))
    )
    haz = None
    if hazmat:
        un, name, cls, pg = shipper.hazmat[0]
        haz = Hazmat(
            un_number=un,
            proper_shipping_name=name,
            hazard_class=cls,
            packing_group=pg,
            emergency_phone=f"1-800-555-01{rng.randint(10, 99)}",
        )
        equipment = rng.choice([Equipment.DRY_VAN_53, Equipment.DRY_VAN_48])
    return Order(
        tender_id=f"{shipper.prefix}-{104200 + number}",
        scac=SCAC,
        shipper=_party(rng, shipper.name, home),
        shipper_reference=f"SI{rng.randint(1000000, 9999999)}",
        stops=stops,
        equipment=equipment,
        weight_lb=rng.randrange(8_000, PAYLOAD_LB[equipment] - 500, 10),
        pieces=rng.randint(6, 26),
        commodity="paint and coatings"
        if hazmat and shipper.prefix == "LHG"
        else ("cleaning concentrate" if hazmat else rng.choice(shipper.commodities)),
        reefer_setpoint_f=rng.randint(34, 38) if equipment == Equipment.REEFER_53 else None,
        hazmat=haz,
        rate_usd=round(rng.uniform(900, 4200), 2),
    )


def _reference(source: Source, n: int) -> str:
    if source == Source.EDI:
        return f"{700000000 + n:09d}"
    if source == Source.PDF:
        return f"ratecon-{n:03d}.pdf"
    return f"<tender-{n:03d}@tenders.example.com>"


def _received(order: Order, days_before: int) -> dt.datetime:
    pickup = order.stops[0].window_start.date() - dt.timedelta(days=days_before)
    return dt.datetime.combine(pickup, dt.time(15, 0), tzinfo=dt.UTC)


def generate(seed: int = 11) -> list[Case]:
    rng = random.Random(seed)
    cases: list[Case] = []
    n = 0
    numbers = itertools.count(1)  # tender ids are unique across every source
    for source in Source:

        def case(kind: str, tender: Tender, of: str | None = None) -> Case:
            nonlocal n
            n += 1
            mine = sum(c.tender.source == tender.source for c in cases)
            return Case(
                id=f"{tender.source.value}-{mine + 1:02d}",
                kind=kind,
                style=n % 3,
                tender=tender,
                duplicate_of=of,
                expected_rules=tuple(EXPECTED_RULES.get(kind, [])),
            )

        valid = []
        for i in range(7):
            order = _order(rng, next(numbers), hazmat=i == 3)
            valid.append(
                case(
                    "valid",
                    Tender(
                        source=source,
                        purpose=Purpose.ORIGINAL,
                        order=order,
                        reference=_reference(source, n + 1),
                        received_at=_received(order, 4),
                    ),
                )
            )
            cases.append(valid[-1])

        first, second, third = valid[0], valid[1], valid[2]
        cases.append(
            case(
                "resend",
                first.tender.model_copy(
                    update={
                        "reference": _reference(source, n + 1),
                        "received_at": first.tender.received_at + dt.timedelta(hours=2),
                    }
                ),
                first.id,
            )
        )
        moved = [
            s.model_copy(
                update={
                    "window_start": s.window_start + dt.timedelta(days=1),
                    "window_end": s.window_end + dt.timedelta(days=1),
                }
            )
            if s.kind == StopKind.DELIVERY
            else s
            for s in second.tender.order.stops
        ]
        cases.append(
            case(
                "change",
                Tender(
                    source=source,
                    purpose=Purpose.CHANGE,
                    order=second.tender.order.model_copy(update={"stops": moved}),
                    reference=_reference(source, n + 1),
                    received_at=second.tender.received_at + dt.timedelta(days=1),
                ),
                second.id,
            )
        )
        cases.append(
            case(
                "cancel",
                third.tender.model_copy(
                    update={
                        "purpose": Purpose.CANCEL,
                        "reference": _reference(source, n + 1),
                        "received_at": third.tender.received_at + dt.timedelta(days=2),
                    }
                ),
                third.id,
            )
        )

        heavy = _order(rng, next(numbers), hazmat=False)
        heavy = heavy.model_copy(
            update={"weight_lb": PAYLOAD_LB[heavy.equipment] + rng.randrange(500, 4000, 10)}
        )
        cases.append(case("overweight", _new(source, heavy, n + 1)))

        rule = LAST_RULE[source]
        broken = _order(rng, next(numbers), hazmat=rule == "hazmat_incomplete")
        if rule == "hazmat_incomplete" and broken.hazmat is not None:
            broken = broken.model_copy(
                update={"hazmat": broken.hazmat.model_copy(update={"un_number": None})}
            )
        else:
            pickup = broken.stops[0]
            early = [
                s.model_copy(
                    update={
                        "window_start": pickup.window_start - dt.timedelta(days=2),
                        "window_end": pickup.window_end - dt.timedelta(days=2),
                    }
                )
                if s.kind == StopKind.DELIVERY
                else s
                for s in broken.stops
            ]
            broken = broken.model_copy(update={"stops": early})
        cases.append(case(rule, _new(source, broken, n + 1)))
    return cases


def _new(source: Source, order: Order, n: int) -> Tender:
    return Tender(
        source=source,
        purpose=Purpose.ORIGINAL,
        order=order,
        reference=_reference(source, n),
        received_at=_received(order, 4),
    )


def _zone(stop: Stop) -> str:
    if stop.time_zone is None:
        return ""
    return stop.window_start.replace(tzinfo=ZoneInfo(stop.time_zone)).tzname() or ""


def _stop_lines(stop: Stop) -> list[str]:
    label = "Pickup" if stop.kind == StopKind.PICKUP else f"Delivery {stop.sequence - 1}"
    p = stop.party
    return [
        f"{label}: {p.name}, {p.street}, {p.city}, {p.state} {p.zip}",
        f"  {stop.window_start:%m/%d/%Y} {stop.window_start:%H:%M} to "
        f"{stop.window_end:%H:%M} {_zone(stop)}, ref {stop.reference}",
    ]


EQUIPMENT_WORDS = {
    Equipment.DRY_VAN_53: "53' dry van",
    Equipment.DRY_VAN_48: "48' dry van",
    Equipment.REEFER_53: "53' reefer",
}


def email_subject(tender: Tender) -> str:
    o = tender.order
    word = {
        Purpose.ORIGINAL: "Load tender",
        Purpose.CHANGE: "UPDATED tender",
        Purpose.CANCEL: "CANCEL tender",
    }[tender.purpose]
    return f"{word} {o.tender_id} / {o.stops[0].party.city} to {o.stops[-1].party.city}"


def render_email(tender: Tender, style: int) -> str:
    """The tender as a shipper's planner would type it, in one of three styles."""
    o = tender.order
    haz = o.hazmat
    hazmat_line = ""
    if haz is not None:
        un = haz.un_number or "UN number to follow"
        hazmat_line = (
            f"HAZMAT: {un}, {haz.proper_shipping_name}, class {haz.hazard_class}, "
            f"PG {haz.packing_group}. Emergency contact {haz.emergency_phone}."
        )
    temp = f" Keep at {o.reefer_setpoint_f}F." if o.reefer_setpoint_f is not None else ""
    action = {
        Purpose.ORIGINAL: "",
        Purpose.CHANGE: "This replaces our earlier tender. ",
        Purpose.CANCEL: "Please CANCEL this load. ",
    }[tender.purpose]
    stops = [line for s in o.stops for line in _stop_lines(s)]
    if style == 0:
        lines = [
            f"{action}Load {o.tender_id}, our ref {o.shipper_reference}.",
            *stops,
            f"{EQUIPMENT_WORDS[o.equipment]}, {o.pieces} pallets, {o.weight_lb:,} lbs, "
            f"{o.commodity}.{temp}",
            f"Rate ${o.rate_usd:,.2f} all in." if o.rate_usd is not None else "",
            hazmat_line,
            f"Thanks, {o.shipper.name} transportation desk",
        ]
    elif style == 1:
        lines = [
            "Hello Example Freight Lines team,",
            "",
            f"{action}Please accept the load below for {o.shipper.name}.",
            f"Shipment {o.tender_id}, shipper reference {o.shipper_reference}.",
            *stops,
            f"Equipment: {EQUIPMENT_WORDS[o.equipment]}. Weight: {o.weight_lb:,} lbs on "
            f"{o.pieces} pallets of {o.commodity}.{temp}",
            f"Agreed rate: ${o.rate_usd:,.2f}." if o.rate_usd is not None else "",
            hazmat_line,
            "",
            "Best regards,",
            f"{o.shipper.name} logistics",
        ]
    else:
        lines = [
            action.strip(),
            f"TENDER ID: {o.tender_id}",
            f"SHIPPER: {o.shipper.name}",
            f"SHIPPER REF: {o.shipper_reference}",
            *stops,
            f"EQUIPMENT: {EQUIPMENT_WORDS[o.equipment]}",
            f"WEIGHT: {o.weight_lb:,} lbs",
            f"PALLETS: {o.pieces}",
            f"COMMODITY: {o.commodity}{temp}",
            f"RATE: ${o.rate_usd:,.2f}" if o.rate_usd is not None else "",
            hazmat_line,
        ]
    return "\n".join(line for line in lines if line is not None).strip() + "\n"
