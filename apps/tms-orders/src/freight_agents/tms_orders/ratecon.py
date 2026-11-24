"""PDF rate confirmations in three layouts, for fixtures. Bytes are reproducible.

Each layout puts the same facts in a different place, the way different shippers'
systems do: a labeled list, a stop table, and a two-column letter.
"""

from __future__ import annotations

from pathlib import Path

from freight_agents.tms_orders.domain import StopKind, Tender
from freight_agents.tms_orders.synth import EQUIPMENT_WORDS, zone_abbreviation
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def _facts(tender: Tender) -> list[tuple[str, str]]:
    o = tender.order
    facts = [
        ("Tender ID", o.tender_id),
        ("Shipper", o.shipper.name),
        ("Shipper reference", o.shipper_reference),
        ("Carrier", f"Example Freight Lines ({o.scac})"),
        ("Equipment", EQUIPMENT_WORDS[o.equipment]),
        ("Weight", f"{o.weight_lb:,} lbs"),
        ("Pallets", str(o.pieces)),
        ("Commodity", o.commodity),
    ]
    if o.reefer_setpoint_f is not None:
        facts.append(("Temperature", f"{o.reefer_setpoint_f}F"))
    if o.rate_usd is not None:
        facts.append(("Rate", f"${o.rate_usd:,.2f}"))
    if o.hazmat is not None:
        h = o.hazmat
        facts.append(
            (
                "Hazardous material",
                f"{h.un_number or 'UN number to follow'}, "
                f"{h.proper_shipping_name}, class {h.hazard_class}, PG {h.packing_group}",
            )
        )
        facts.append(("Emergency contact", h.emergency_phone or ""))
    return facts


def _title(tender: Tender) -> str:
    return {"original": "RATE CONFIRMATION", "change": "REVISED RATE CONFIRMATION",
            "cancel": "CANCELLATION OF LOAD"}[tender.purpose.value]  # fmt: skip


def render_pdf(tender: Tender, layout: int, path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=LETTER, invariant=True)
    page.setTitle(f"{_title(tender)} {tender.order.tender_id}")
    y = 740.0

    def line(text: str, x: float = 54, size: int = 10, font: str = "Helvetica") -> None:
        nonlocal y
        page.setFont(font, size)
        page.drawString(x, y, text)
        y -= size + 6

    line(_title(tender), size=16, font="Helvetica-Bold")
    if layout == 0:
        for label, value in _facts(tender):
            line(f"{label}: {value}")
        for stop in tender.order.stops:
            p = stop.party
            kind = "Pickup" if stop.kind == StopKind.PICKUP else "Delivery"
            line(f"{kind} {stop.sequence}: {p.name}, {p.street}, {p.city}, {p.state} {p.zip}")
            line(f"Window {stop.window_start:%m/%d/%Y} {stop.window_start:%H:%M} to "
                 f"{stop.window_end:%H:%M} {zone_abbreviation(stop)}, ref {stop.reference}",
                 x=72)  # fmt: skip
    elif layout == 1:
        for label, value in _facts(tender):
            line(f"{label.upper():<20} {value}", font="Courier")
        line("STOP  TYPE      DATE        WINDOW            REF", font="Courier-Bold")
        for stop in tender.order.stops:
            p = stop.party
            kind = "PICKUP" if stop.kind == StopKind.PICKUP else "DELIVER"
            line(f"{stop.sequence:<5} {kind:<9} {stop.window_start:%m/%d/%Y}  "
                 f"{stop.window_start:%H:%M}-{stop.window_end:%H:%M} {zone_abbreviation(stop):<4} "
                 f"{stop.reference}", font="Courier")  # fmt: skip
            line(f"      {p.name}, {p.street}, {p.city}, {p.state} {p.zip}", font="Courier")
    else:
        facts = _facts(tender)
        top = y
        for i, (label, value) in enumerate(facts):
            column = 54 if i % 2 == 0 else 320
            page.setFont("Helvetica", 9)
            page.drawString(column, top - 16 * (i // 2), f"{label}: {value}")
        y = top - 16 * ((len(facts) + 1) // 2) - 10
        line("Please arrange the following stops.", font="Helvetica-Oblique")
        for stop in tender.order.stops:
            p = stop.party
            verb = "Load at" if stop.kind == StopKind.PICKUP else "Deliver to"
            line(f"Stop {stop.sequence}. {verb} {p.name}, {p.street}, {p.city}, {p.state} {p.zip}",
                 size=9)  # fmt: skip
            line(f"between {stop.window_start:%H:%M} and {stop.window_end:%H:%M} "
                 f"{zone_abbreviation(stop)} on {stop.window_start:%m/%d/%Y} "
                 f"(ref {stop.reference})", x=72, size=9)  # fmt: skip
    page.showPage()
    page.save()
