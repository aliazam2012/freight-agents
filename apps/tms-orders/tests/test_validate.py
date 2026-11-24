import datetime as dt

import pytest
from freight_agents.tms_orders.domain import Equipment, Hazmat, Order, StopKind
from freight_agents.tms_orders.synth import generate
from freight_agents.tms_orders.validate import Finding, validate_order

CASES = generate(seed=11)
NOW = dt.datetime(2026, 11, 23, 12, 0, tzinfo=dt.UTC)


def rules(order: Order, now: dt.datetime = NOW) -> list[str]:
    return [f.rule for f in validate_order(order, now) if f.severity != "notice"]


def base() -> Order:
    return next(
        c for c in CASES if c.kind == "valid" and c.tender.order.hazmat is None
    ).tender.order


def test_every_seeded_tender_gets_exactly_its_expected_findings() -> None:
    for case in CASES:
        assert rules(case.tender.order) == list(case.expected_rules), case.id


def test_every_finding_names_a_source() -> None:
    for case in CASES:
        for finding in validate_order(case.tender.order, NOW):
            assert isinstance(finding, Finding)
            assert finding.source.startswith(("https://", "Planning assumption"))


def _stop(order: Order, i: int, **update: object) -> Order:
    stops = list(order.stops)
    stops[i] = stops[i].model_copy(update=update)
    return order.model_copy(update={"stops": stops})


def test_address_rules() -> None:
    order = base()
    assert rules(
        _stop(order, 0, party=order.stops[0].party.model_copy(update={"zip": "6063"}))
    ) == ["address.zip"]
    plus4 = _stop(order, 0, party=order.stops[0].party.model_copy(update={"zip": "60632-1234"}))
    assert rules(plus4) == []
    assert "address.state" in rules(order.model_copy(
        update={"shipper": order.shipper.model_copy(update={"state": "ZZ"})}))  # fmt: skip
    outside = _stop(order, 1, time_zone=None)
    assert rules(outside) == ["address.time_zone"]


def test_windows_compare_in_utc_across_zones() -> None:
    # Pickup in Los Angeles at 09:00 PST is 17:00 UTC. A Boston delivery window that ends at
    # 10:00 EST the same day ends at 15:00 UTC, before the truck is even loaded, although the
    # local clock times (10:00 after 09:00) look fine.
    order = base()
    day = dt.date(2026, 12, 10)
    pickup = order.stops[0].model_copy(update={
        "window_start": dt.datetime.combine(day, dt.time(9)),
        "window_end": dt.datetime.combine(day, dt.time(11)),
        "time_zone": "America/Los_Angeles"})  # fmt: skip
    delivery = order.stops[1].model_copy(update={
        "window_start": dt.datetime.combine(day, dt.time(8)),
        "window_end": dt.datetime.combine(day, dt.time(10)),
        "time_zone": "America/New_York"})  # fmt: skip
    bad = order.model_copy(update={"stops": [pickup, delivery]})
    assert "window.delivery_before_pickup" in rules(bad)


def test_arizona_offset_changes_with_daylight_time() -> None:
    # In July, Denver is UTC-6 and Phoenix UTC-7: a Phoenix delivery ending 10:30 local
    # (17:30 UTC) ends after a Denver pickup starting 11:00 local (17:00 UTC).
    order = base()
    day = dt.date(2027, 7, 14)
    pickup = order.stops[0].model_copy(update={
        "window_start": dt.datetime.combine(day, dt.time(11)),
        "window_end": dt.datetime.combine(day, dt.time(13)),
        "time_zone": "America/Denver"})  # fmt: skip
    delivery = order.stops[1].model_copy(update={
        "window_start": dt.datetime.combine(day, dt.time(6)),
        "window_end": dt.datetime.combine(day, dt.time(10, 30)),
        "time_zone": "America/Phoenix"})  # fmt: skip
    later = order.model_copy(update={"stops": [pickup, delivery]})
    assert "window.delivery_before_pickup" not in rules(later)


def test_a_window_may_cross_midnight_but_not_run_backwards() -> None:
    order = base()
    start = order.stops[0].window_start.replace(hour=22)
    overnight = _stop(order, 0, window_start=start, window_end=start + dt.timedelta(hours=4))
    assert "window.order" not in rules(overnight)
    backwards = _stop(order, 0, window_end=order.stops[0].window_start - dt.timedelta(hours=1))
    assert "window.order" in rules(backwards)


def test_transit_and_past_windows_go_to_review() -> None:
    order = base()
    pickup = order.stops[0]
    rushed = _stop(order, 1, window_start=pickup.window_start + dt.timedelta(hours=6),
                   window_end=pickup.window_end + dt.timedelta(hours=6))  # fmt: skip
    found = {f.rule: f for f in validate_order(rushed, NOW)}
    if "window.transit" in found:
        assert found["window.transit"].severity == "review"
    late = validate_order(order, pickup.window_end.replace(tzinfo=dt.UTC) + dt.timedelta(days=1))
    assert [f.severity for f in late if f.rule == "window.past"] == ["review"]


def test_weight_and_reefer_rules() -> None:
    order = base().model_copy(update={"equipment": Equipment.DRY_VAN_53, "reefer_setpoint_f": None})
    assert rules(order.model_copy(update={"weight_lb": 44_000})) == []
    assert rules(order.model_copy(update={"weight_lb": 44_010})) == ["weight.payload"]
    assert rules(order.model_copy(update={"pieces": 0})) == ["load.pieces"]
    reefer = order.model_copy(update={"equipment": Equipment.REEFER_53})
    assert rules(reefer.model_copy(update={"weight_lb": 40_000})) == ["reefer.setpoint"]
    assert rules(order.model_copy(update={"weight_lb": 40_000, "reefer_setpoint_f": 36})) == [
        "reefer.setpoint_on_dry_van"
    ]


HAZMAT = Hazmat(un_number="UN1263", proper_shipping_name="Paint", hazard_class="3",
                packing_group="II", emergency_phone="1-800-555-0142")  # fmt: skip


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"un_number": None}, "hazmat.un_number"),
        ({"un_number": "1263"}, "hazmat.un_number"),
        ({"proper_shipping_name": None}, "hazmat.shipping_name"),
        ({"hazard_class": "10"}, "hazmat.class"),
        ({"packing_group": None}, "hazmat.packing_group"),
        ({"packing_group": "IV"}, "hazmat.packing_group"),
        ({"emergency_phone": None}, "hazmat.emergency_phone"),
        ({"emergency_phone": "call dispatch"}, "hazmat.emergency_phone"),
    ],
)
def test_each_missing_shipping_paper_element_blocks(change: dict[str, object], rule: str) -> None:
    order = base().model_copy(update={"hazmat": HAZMAT.model_copy(update=change),
                                      "weight_lb": 2_000})  # fmt: skip
    found = [f for f in validate_order(order, NOW) if f.rule == rule]
    assert [f.severity for f in found] == ["block"]


def test_explosives_and_peroxides_take_no_packing_group() -> None:
    order = base().model_copy(update={"hazmat": HAZMAT.model_copy(
        update={"hazard_class": "1.4", "packing_group": None}), "weight_lb": 900})  # fmt: skip
    assert rules(order) == []


@pytest.mark.parametrize(
    ("hazard_class", "weight", "placards"),
    [
        ("3", 1_000, False),
        ("3", 1_001, True),
        ("8", 1_500, True),
        ("2.3", 10, True),
        ("1.4", 900, False),
        ("4.3", 50, True),
    ],
)
def test_placards_follow_tables_1_and_2(hazard_class: str, weight: int, placards: bool) -> None:
    hazmat = HAZMAT.model_copy(update={"hazard_class": hazard_class,
                                       "packing_group": None if hazard_class.startswith("1")
                                       else "II"})  # fmt: skip
    order = base().model_copy(update={"hazmat": hazmat, "weight_lb": weight})
    notices = [f.rule for f in validate_order(order, NOW) if f.severity == "notice"]
    assert ("hazmat.placards" in notices) is placards


def test_stops_must_start_with_a_pickup_and_count_up() -> None:
    order = base()
    swapped = order.model_copy(update={"stops": [
        order.stops[1].model_copy(update={"sequence": 1}),
        order.stops[0].model_copy(update={"sequence": 2})]})  # fmt: skip
    assert "stops.sequence" in rules(swapped)
    assert all(s.kind in (StopKind.PICKUP, StopKind.DELIVERY) for s in order.stops)
