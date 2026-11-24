import pytest
from freight_agents.integrations.x12 import Separators, X12Error, parse_interchange
from freight_agents.tms_orders.domain import Purpose, Source
from freight_agents.tms_orders.edi204 import parse_204, write_204, write_990
from freight_agents.tms_orders.synth import generate

EDI = [c for c in generate(seed=11) if c.tender.source == Source.EDI]


@pytest.mark.parametrize("case", EDI, ids=[c.id for c in EDI])
def test_every_edi_tender_round_trips(case) -> None:  # type: ignore[no-untyped-def]
    (back,) = parse_204(write_204(case.tender))
    assert back == case.tender


def test_other_separators_and_line_breaks_read_the_same() -> None:
    tender = EDI[0].tender
    other = write_204(tender, separators=Separators(element="|", component=":", segment="\n"))
    wrapped = write_204(tender).replace("~", "~\r\n")
    assert parse_204(other) == parse_204(wrapped) == [tender]


def test_purpose_and_stop_codes_from_either_published_guide() -> None:
    text = write_204(EDI[0].tender)
    assert parse_204(text.replace("B2A*00*", "B2A*01*"))[0].purpose == Purpose.CANCEL
    assert parse_204(text.replace("B2A*00*", "B2A*04*"))[0].purpose == Purpose.CHANGE
    assert parse_204(text.replace("B2A*00*", "B2A*05*"))[0].purpose == Purpose.CHANGE
    loads = parse_204(text.replace("S5*1*CL", "S5*1*LD").replace("S5*2*CU", "S5*2*UL"))
    assert loads[0].order.stops == EDI[0].tender.order.stops
    with pytest.raises(X12Error) as err:
        parse_204(text.replace("B2A*00*", "B2A*77*"))
    assert err.value.segment == "B2A"


def test_unsupported_equipment_is_refused_by_segment() -> None:
    tender = EDI[0].tender
    length = "4800" if tender.order.equipment == "dry_van_48" else "5300"
    with pytest.raises(X12Error) as err:
        parse_204(write_204(tender).replace(f"*{length}~", "*2800~"))
    assert err.value.segment == "N7"


def test_a_city_outside_the_network_leaves_the_time_zone_open() -> None:
    tender = EDI[0].tender
    stop = tender.order.stops[-1]
    text = write_204(tender).replace(f"N4*{stop.party.city}*", "N4*Smallville*")
    order = parse_204(text)[0].order
    assert order.stops[-1].time_zone is None


def test_values_holding_a_separator_are_refused_when_writing() -> None:
    order = EDI[0].tender.order.model_copy(update={"commodity": "chairs~tables"})
    with pytest.raises(X12Error):
        write_204(EDI[0].tender.model_copy(update={"order": order}))


@pytest.mark.parametrize(("accept", "code"), [(True, "A"), (False, "D")])
def test_a_990_answers_the_tender(accept: bool, code: str) -> None:
    tender = EDI[0].tender
    ix = parse_interchange(write_990(tender, accept=accept, control="1", when="202612091600"))
    (group,) = ix.groups
    assert group.functional_id == "GF"
    (ts,) = group.sets
    assert ts.set_id == "990"
    assert ts.body[0] == ["B1", tender.order.scac, tender.order.tender_id, "20261209", code]


def test_two_tenders_in_one_interchange() -> None:
    from freight_agents.integrations.x12 import write_interchange

    a, b = EDI[0].tender, EDI[1].tender
    bodies = [parse_interchange(write_204(t)).groups[0].sets[0].body for t in (a, b)]
    text = write_interchange(
        sender="LHG",
        receiver="EXFL",
        control=a.reference,
        group_control="1",
        when=f"{a.received_at:%Y%m%d%H%M}",
        functional_id="SM",
        sets=[("204", "0001", bodies[0]), ("204", "0002", bodies[1])],
    )
    assert [t.order for t in parse_204(text)] == [a.order, b.order]
