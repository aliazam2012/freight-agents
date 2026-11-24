"""X12 204 load tenders to `Tender`, and 990 responses back.

Segment use follows two published partner guides (summaries in the knowledge
package, docs/orders): CN's 204 guide (B2, B2A 00/01/04, G62 date qualifiers 10,
38, 68 and 54 with LT local time, S5 CL and CU, N1 SH, SF and ST, N7 with N715
length 5300 for 53 feet, AT8, L3) and C.H. Robinson's 204 and truckload 990
specifications (G62 time qualifiers 4, 5, K and L, S5 LD and UL, N711 TL, N713
temperature, L11 SI and PU, LH1 with LH103 UN number and LH110 packing group, 990
B1 with B104 A or D).

Where both guides are silent this made-up partner sets its own conventions, as
every real partner guide does: a reefer is N711 TL with an N713 setpoint such as
36F; the hazard class is LH2, the proper shipping name LH3, the emergency phone a
G61 with function HM; the rate is L305; the commodity is L5. A stop's time zone
is not sent: it comes from the stop's city in the place table, and an unknown
city leaves it open for review.
"""

from __future__ import annotations

import datetime as dt

from freight_agents.integrations.x12 import (
    DEFAULT,
    Segment,
    Separators,
    X12Error,
    parse_interchange,
    write_interchange,
)
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
from freight_agents.tms_orders.places import zone_for

PURPOSE_CODE = {Purpose.ORIGINAL: "00", Purpose.CANCEL: "01", Purpose.CHANGE: "04"}
PURPOSE_OF = {"00": Purpose.ORIGINAL, "01": Purpose.CANCEL, "04": Purpose.CHANGE,
              "05": Purpose.CHANGE}  # fmt: skip
PICKUP_REASONS = {"CL", "LD", "PL"}
DELIVERY_REASONS = {"CU", "UL", "PU"}
LENGTH = {Equipment.DRY_VAN_53: "5300", Equipment.DRY_VAN_48: "4800",
          Equipment.REEFER_53: "5300"}  # fmt: skip


def _party_segments(code: str, party: Party) -> list[Segment]:
    return [
        ["N1", code, party.name],
        ["N3", party.street],
        ["N4", party.city, party.state, party.zip],
    ]


def _stop_segments(stop: Stop, order: Order) -> list[Segment]:
    pickup = stop.kind == StopKind.PICKUP
    out: list[Segment] = [["S5", str(stop.sequence), "CL" if pickup else "CU"]]
    if stop.reference:
        out.append(["L11", stop.reference, "PU" if pickup else "DO"])
    start, end = stop.window_start, stop.window_end
    out.append(["G62", "10" if pickup else "68", f"{start:%Y%m%d}", "4" if pickup else "5",
                f"{start:%H%M}", "LT"])  # fmt: skip
    out.append(["G62", "38" if pickup else "54", f"{end:%Y%m%d}", "K" if pickup else "L",
                f"{end:%H%M}", "LT"])  # fmt: skip
    out.extend(_party_segments("SF" if pickup else "ST", stop.party))
    if pickup:
        out.append(["AT8", "G", "L", str(order.weight_lb), str(order.pieces)])
    return out


def _body(order: Order, purpose: Purpose) -> list[Segment]:
    temp = f"{order.reefer_setpoint_f}F" if order.reefer_setpoint_f is not None else ""
    body: list[Segment] = [
        ["B2", "", order.scac, "", order.tender_id, "L", "PP"],
        ["B2A", PURPOSE_CODE[purpose], "LT"],
        ["L11", order.shipper_reference, "SI"],
        *_party_segments("SH", order.shipper),
        ["N7", "", "0", *[""] * 8, "TL", "", temp, "", LENGTH[order.equipment]],
        ["L5", "1", order.commodity],
    ]
    for stop in order.stops:
        body.extend(_stop_segments(stop, order))
    if order.hazmat is not None:
        h = order.hazmat
        body.append(["LH1", "PL", str(order.pieces), h.un_number or "", *[""] * 6,
                     h.packing_group or ""])  # fmt: skip
        body.append(["LH2", h.hazard_class or ""])
        body.append(["LH3", h.proper_shipping_name or "", "D"])
        body.append(["G61", "HM", "EMERGENCY CONTACT", "TE", h.emergency_phone or ""])
    rate = f"{order.rate_usd:.2f}" if order.rate_usd is not None else ""
    body.append(["L3", str(order.weight_lb), "G", "", "", rate, *[""] * 5, str(order.pieces),
                 "L"])  # fmt: skip
    return body


def write_204(tender: Tender, separators: Separators = DEFAULT) -> str:
    """The tender as an X12 204 interchange; its reference is the interchange control number."""
    body = _body(tender.order, tender.purpose)
    reserved = {separators.element, separators.segment, separators.component}
    for segment in body:
        for value in segment:
            if reserved & set(value):
                raise X12Error(segment[0], f"value {value!r} holds a separator character")
    return write_interchange(
        sender=tender.order.shipper.name.split()[0].upper()[:15],
        receiver=tender.order.scac,
        control=tender.reference,
        group_control=str(int(tender.reference) % 1_000_000_000),
        when=f"{tender.received_at.astimezone(dt.UTC):%Y%m%d%H%M}",
        functional_id="SM",
        sets=[("204", "0001", body)],
        separators=separators,
    )


def write_990(tender: Tender, *, accept: bool, control: str, when: str) -> str:
    """The carrier's answer: B1 with B104 A (accepted) or D (declined)."""
    o = tender.order
    body: list[Segment] = [["B1", o.scac, o.tender_id, when[:8], "A" if accept else "D"]]
    return write_interchange(
        sender=o.scac, receiver=o.shipper.name.split()[0].upper()[:15], control=control,
        group_control=control, when=when, functional_id="GF", sets=[("990", "0001", body)],
    )  # fmt: skip


def _get(segment: Segment, index: int) -> str:
    return segment[index] if index < len(segment) else ""


def _when(date: str, time: str) -> dt.datetime:
    return dt.datetime.strptime(date + time, "%Y%m%d%H%M")


class _Builder:
    def __init__(self) -> None:
        self.header: dict[str, str] = {}
        self.parties: dict[str, dict[str, str]] = {}
        self.stops: list[dict[str, str]] = []
        self.hazmat: dict[str, str] = {}
        self.current: dict[str, str] | None = None  # the party being read

    def party(self, code: str, name: str) -> None:
        self.current = {"name": name}
        if self.stops and code in ("SF", "ST"):
            self.stops[-1]["party"] = code
            self.stops[-1].update({f"party_{k}": v for k, v in self.current.items()})
        self.parties[code] = self.current

    def address(self, **fields: str) -> None:
        if self.current is None:
            return
        self.current.update(fields)
        if self.stops and "party" in self.stops[-1]:
            self.stops[-1].update({f"party_{k}": v for k, v in fields.items()})


def _party(fields: dict[str, str], prefix: str = "") -> Party:
    return Party(
        name=fields.get(f"{prefix}name", ""),
        street=fields.get(f"{prefix}street", ""),
        city=fields.get(f"{prefix}city", ""),
        state=fields.get(f"{prefix}state", ""),
        zip=fields.get(f"{prefix}zip", ""),
    )


def _tender(body: list[Segment], reference: str, received: dt.datetime) -> Tender:
    b = _Builder()
    for seg in body:
        tag = seg[0]
        if tag == "B2":
            b.header.update(scac=_get(seg, 2), tender_id=_get(seg, 4))
        elif tag == "B2A":
            if _get(seg, 1) not in PURPOSE_OF:
                raise X12Error("B2A", f"unknown transaction set purpose {_get(seg, 1)!r}")
            b.header["purpose"] = _get(seg, 1)
        elif tag == "L11" and not b.stops and _get(seg, 2) == "SI":
            b.header["shipper_reference"] = _get(seg, 1)
        elif tag == "L11" and b.stops:
            b.stops[-1]["reference"] = _get(seg, 1)
        elif tag == "N1":
            b.party(_get(seg, 1), _get(seg, 2))
        elif tag == "N3":
            b.address(street=_get(seg, 1))
        elif tag == "N4":
            b.address(city=_get(seg, 1), state=_get(seg, 2), zip=_get(seg, 3))
        elif tag == "N7":
            b.header.update(length=_get(seg, 15), temp=_get(seg, 13))
        elif tag == "L5":
            b.header["commodity"] = _get(seg, 2)
        elif tag == "S5":
            reason = _get(seg, 2)
            if reason not in PICKUP_REASONS | DELIVERY_REASONS:
                raise X12Error("S5", f"unknown stop reason {reason!r}")
            b.stops.append({"sequence": _get(seg, 1), "reason": reason})
            b.current = None
        elif tag == "G62" and b.stops:
            key = "start" if _get(seg, 1) in ("10", "68") else "end"
            b.stops[-1][key] = _get(seg, 2) + _get(seg, 4)
        elif tag == "AT8":
            b.header.setdefault("weight", _get(seg, 3))
            b.header.setdefault("pieces", _get(seg, 4))
        elif tag == "LH1":
            b.hazmat.update(un=_get(seg, 3), pg=_get(seg, 10))
        elif tag == "LH2":
            b.hazmat["class"] = _get(seg, 1)
        elif tag == "LH3":
            b.hazmat["name"] = _get(seg, 1)
        elif tag == "G61" and _get(seg, 1) == "HM":
            b.hazmat["phone"] = _get(seg, 4)
        elif tag == "L3":
            b.header.update(weight=_get(seg, 1), pieces=_get(seg, 11), rate=_get(seg, 5))

    temp, length = b.header.get("temp", ""), b.header.get("length", "")
    if temp:
        if length != "5300":
            raise X12Error("N7", f"no reefer of length {length!r} in this network")
        equipment = Equipment.REEFER_53
    elif length in ("5300", "4800"):
        equipment = Equipment.DRY_VAN_53 if length == "5300" else Equipment.DRY_VAN_48
    else:
        raise X12Error("N7", f"no trailer of length {length!r} in this network")

    stops = []
    for s in b.stops:
        party = _party(s, "party_")
        stops.append(
            Stop(
                sequence=int(s["sequence"]),
                kind=StopKind.PICKUP if s["reason"] in PICKUP_REASONS else StopKind.DELIVERY,
                party=party,
                window_start=_when(s["start"][:8], s["start"][8:]),
                window_end=_when(s["end"][:8], s["end"][8:]),
                time_zone=zone_for(party.city, party.state),
                reference=s.get("reference") or None,
            )
        )
    hazmat = None
    if b.hazmat:
        h = b.hazmat
        hazmat = Hazmat(
            un_number=h.get("un") or None,
            proper_shipping_name=h.get("name") or None,
            hazard_class=h.get("class") or None,
            packing_group=h.get("pg") or None,
            emergency_phone=h.get("phone") or None,
        )
    rate = b.header.get("rate", "")
    order = Order(
        tender_id=b.header.get("tender_id", ""),
        scac=b.header.get("scac", ""),
        shipper=_party(b.parties.get("SH", {})),
        shipper_reference=b.header.get("shipper_reference", ""),
        stops=stops,
        equipment=equipment,
        weight_lb=int(float(b.header.get("weight") or 0)),
        pieces=int(b.header.get("pieces") or 0),
        commodity=b.header.get("commodity", ""),
        reefer_setpoint_f=int(temp.rstrip("F")) if temp else None,
        hazmat=hazmat,
        rate_usd=float(rate) if rate else None,
    )
    return Tender(
        source=Source.EDI,
        purpose=PURPOSE_OF[b.header.get("purpose", "00")],
        order=order,
        reference=reference,
        received_at=received,
    )


def parse_204(text: str) -> list[Tender]:
    """Every 204 in an interchange as a Tender; the envelope is checked first."""
    ix = parse_interchange(text)
    tenders = []
    for group in ix.groups:
        received = _when(group.date, group.time).replace(tzinfo=dt.UTC)
        for ts in group.sets:
            if ts.set_id == "204":
                tenders.append(_tender(ts.body, ix.control, received))
    return tenders
