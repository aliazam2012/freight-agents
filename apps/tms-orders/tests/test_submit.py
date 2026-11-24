import datetime as dt

import pytest
from fastapi.testclient import TestClient
from freight_agents.mock_tms.app import create_app
from freight_agents.tms_orders.submit import submit
from freight_agents.tms_orders.synth import generate
from freight_agents.tms_orders.tms import CircuitBreaker, HttpTms, fingerprint

CASES = generate(seed=11)
BY_ID = {c.id: c for c in CASES}


@pytest.fixture
def tms() -> HttpTms:
    clock = lambda: dt.datetime(2026, 12, 1, tzinfo=dt.UTC)  # noqa: E731
    return HttpTms(TestClient(create_app()), breaker=CircuitBreaker(clock=clock),
                   sleep=lambda s: None, clock=clock)  # fmt: skip


def variant(kind: str):  # type: ignore[no-untyped-def]
    case = next(c for c in CASES if c.kind == kind)
    return BY_ID[case.duplicate_of or ""].tender, case.tender


def test_an_original_creates_one_order_and_running_it_again_creates_none(tms: HttpTms) -> None:
    tender = CASES[0].tender
    first = submit(tms, tender)
    again = submit(tms, tender)
    assert first.outcome == "created"
    assert again.outcome == "duplicate"
    assert again.receipt is not None
    assert first.receipt is not None
    assert again.receipt.order_id == first.receipt.order_id
    assert len(tms.find(fingerprint(tender.order))) == 1


def test_a_resent_tender_under_a_new_reference_maps_to_the_existing_order(tms: HttpTms) -> None:
    original, resend = variant("resend")
    created = submit(tms, original)
    again = submit(tms, resend)
    assert again.outcome == "duplicate"
    assert again.receipt is not None
    assert created.receipt is not None
    assert again.receipt.order_id == created.receipt.order_id


def test_a_change_updates_the_order_and_a_cancel_closes_it(tms: HttpTms) -> None:
    original, change = variant("change")
    submit(tms, original)
    changed = submit(tms, change)
    assert changed.outcome == "changed"
    assert changed.receipt is not None
    assert changed.receipt.version == 2
    assert submit(tms, change).outcome == "changed"  # a rerun replays, no third version
    assert tms.find(fingerprint(change.order))[0].version == 2
    original, cancel = variant("cancel")
    submit(tms, original)
    assert submit(tms, cancel).outcome == "cancelled"
    assert submit(tms, cancel).outcome == "cancelled"


@pytest.mark.parametrize("kind", ["change", "cancel"])
def test_a_change_or_cancel_for_an_unknown_order_goes_to_review(tms: HttpTms, kind: str) -> None:
    _, tender = variant(kind)
    result = submit(tms, tender)
    assert result.outcome == "needs_review"
    assert result.receipt is None
    assert tms.find(fingerprint(tender.order)) == []


def test_a_new_original_for_a_cancelled_load_is_a_new_order(tms: HttpTms) -> None:
    original, cancel = variant("cancel")
    submit(tms, original)
    submit(tms, cancel)
    again = submit(tms, original.model_copy(update={"reference": "rebooked-1"}))
    assert again.outcome == "needs_review"
