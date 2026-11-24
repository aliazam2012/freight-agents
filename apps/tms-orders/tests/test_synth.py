import itertools
from collections import Counter

from freight_agents.tms_orders.domain import Order, Purpose, Source, StopKind
from freight_agents.tms_orders.places import PLACES
from freight_agents.tms_orders.synth import PAYLOAD_LB, generate, render_email


def test_same_seed_same_tenders_and_a_new_seed_differs() -> None:
    assert generate(seed=11) == generate(seed=11)
    assert generate(seed=11) != generate(seed=12)


def test_every_gold_order_round_trips_through_the_schema() -> None:
    for case in generate(seed=11):
        assert Order.model_validate_json(case.tender.order.model_dump_json()) == case.tender.order


def test_twelve_tenders_per_source_with_every_kind_of_case() -> None:
    cases = generate(seed=11)
    assert Counter(c.tender.source for c in cases) == {s: 12 for s in Source}
    for source in Source:
        mine = [c for c in cases if c.tender.source == source]
        assert Counter(c.kind for c in mine) == {
            "valid": 7,
            "resend": 1,
            "change": 1,
            "cancel": 1,
            "overweight": 1,
            "bad_window": 1,
        } or Counter(c.kind for c in mine) == {
            "valid": 7,
            "resend": 1,
            "change": 1,
            "cancel": 1,
            "overweight": 1,
            "hazmat_incomplete": 1,
        }
    assert any(c.kind == "hazmat_incomplete" for c in cases)
    assert any(c.kind == "bad_window" for c in cases)


def test_variants_point_at_their_original() -> None:
    cases = generate(seed=11)
    by_id = {c.id: c for c in cases}
    for c in cases:
        if c.kind in ("resend", "change", "cancel"):
            original = by_id[c.duplicate_of or ""]
            assert original.tender.order.shipper_reference == c.tender.order.shipper_reference
            assert original.tender.reference != c.tender.reference
        else:
            assert c.duplicate_of is None
    purposes = {c.kind: c.tender.purpose for c in cases}
    assert purposes["resend"] == Purpose.ORIGINAL
    assert purposes["change"] == Purpose.CHANGE
    assert purposes["cancel"] == Purpose.CANCEL


def test_valid_orders_respect_limits_and_invalid_ones_break_one() -> None:
    for c in generate(seed=11):
        order = c.tender.order
        pickups = [s for s in order.stops if s.kind == StopKind.PICKUP]
        deliveries = [s for s in order.stops if s.kind == StopKind.DELIVERY]
        assert pickups
        assert deliveries
        if c.kind == "overweight":
            assert order.weight_lb > PAYLOAD_LB[order.equipment]
            continue
        assert order.weight_lb <= PAYLOAD_LB[order.equipment]
        if c.kind == "bad_window":
            assert deliveries[0].window_end < pickups[-1].window_start
        if c.kind == "hazmat_incomplete":
            assert order.hazmat is not None
            assert order.hazmat.un_number is None
        if order.equipment == "reefer_53":
            assert order.reefer_setpoint_f is not None


def test_every_stop_is_a_known_place_with_its_time_zone() -> None:
    known = {(p.city, p.state): p.time_zone for p in PLACES}
    for c in generate(seed=11):
        for stop in c.tender.order.stops:
            assert stop.time_zone == known[(stop.party.city, stop.party.state)]


def test_an_email_tender_states_every_field_a_planner_needs() -> None:
    for c in generate(seed=11):
        if c.tender.source != Source.EMAIL:
            continue
        text = render_email(c.tender, style=c.style)
        order = c.tender.order
        assert order.shipper_reference in text
        assert f"{order.weight_lb:,}" in text
        for stop in order.stops:
            assert stop.party.zip in text
            assert stop.window_start.strftime("%m/%d/%Y") in text
        if order.hazmat and order.hazmat.un_number:
            assert order.hazmat.un_number in text


def test_tender_ids_are_unique_except_for_variants_of_one_order() -> None:
    cases = generate(seed=11)
    originals = [c for c in cases if c.duplicate_of is None]
    ids = [c.tender.order.tender_id for c in originals]
    assert len(ids) == len(set(ids))
    references = [c.tender.reference for c in cases]
    assert len(references) == len(set(references))


def test_valid_deliveries_leave_a_drivers_transit_time() -> None:
    from freight_agents.tms_orders.places import transit_days, zone_place

    for c in generate(seed=11):
        if c.kind == "bad_window":
            continue
        stops = c.tender.order.stops
        for before, after in itertools.pairwise(stops):
            days = transit_days(zone_place(before.party), zone_place(after.party))
            assert (after.window_start.date() - before.window_start.date()).days >= days


def test_transit_days_follow_distance() -> None:
    from freight_agents.tms_orders.places import PLACES, miles, transit_days

    by = {p.code: p for p in PLACES}
    assert 700 < miles(by["CHI"], by["DAL"]) < 1100
    assert transit_days(by["DEN"], by["NWK"]) >= 3
    assert transit_days(by["CHI"], by["MEM"]) == 2
