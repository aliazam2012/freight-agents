import datetime as dt
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from freight_agents.mock_tms.app import create_app
from freight_agents.tms_orders.domain import Source
from freight_agents.tms_orders.synth import generate
from freight_agents.tms_orders.tms import (
    CircuitBreaker,
    HttpTms,
    RetryBudget,
    TmsError,
    TmsUnavailable,
    fingerprint,
)

CASES = generate(seed=11)
ORDER = CASES[0].tender.order
FP = fingerprint(ORDER)
CREATED = {"order_id": "ORD-000001", "status": "open", "version": 1, "fingerprint": FP,
           "tender_reference": "r1", "order": {}, "created_at": "2026-12-01T09:00:00Z",
           "updated_at": "2026-12-01T09:00:00Z"}  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 12, 1, 9, 0, tzinfo=dt.UTC)
        self.slept: list[float] = []

    def __call__(self) -> dt.datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


def scripted(*answers: Any) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(answers)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body, headers = answer if len(answer) == 3 else (*answer, {})
        return httpx.Response(status, json=body, headers=headers)

    client = httpx.Client(transport=httpx.MockTransport(handle), base_url="http://tms.test")
    return client, seen


def tms(client: httpx.Client, clock: Clock, **kw: Any) -> HttpTms:
    return HttpTms(client, breaker=CircuitBreaker(clock=clock), sleep=clock.sleep, clock=clock,
                   **kw)  # fmt: skip


def test_happy_path() -> None:
    client, seen = scripted((201, CREATED))
    receipt = tms(client, Clock()).create(ORDER, FP, "r1", key="k-1")
    assert receipt.order_id == "ORD-000001"
    assert seen[0].headers["Idempotency-Key"] == '"k-1"'
    assert json.loads(seen[0].content)["fingerprint"] == FP


def test_server_errors_and_timeouts_retry_with_the_same_key() -> None:
    clock = Clock()
    client, seen = scripted((503, {}), httpx.ReadTimeout("slow"), (201, CREATED))
    assert tms(client, clock).create(ORDER, FP, "r1", key="k-1").order_id == "ORD-000001"
    assert len(seen) == 3
    assert {r.headers["Idempotency-Key"] for r in seen} == {'"k-1"'}
    assert len(clock.slept) == 2


@pytest.mark.parametrize("status", [400, 404, 422])
def test_client_errors_are_not_retried(status: int) -> None:
    client, seen = scripted((status, {"title": "no", "status": status}))
    with pytest.raises(TmsError) as err:
        tms(client, Clock()).create(ORDER, FP, "r1", key="k-1")
    assert err.value.status == status
    assert len(seen) == 1


def test_a_429_trips_the_breaker_and_honors_retry_after() -> None:
    clock = Clock()
    client, seen = scripted((429, {}, {"Retry-After": "120"}), (201, CREATED))
    breaker = CircuitBreaker(clock=clock)
    client_tms = HttpTms(client, breaker=breaker, sleep=clock.sleep, clock=clock)
    with pytest.raises(TmsUnavailable):
        client_tms.create(ORDER, FP, "r1", key="k-1")
    assert breaker.is_open
    with pytest.raises(TmsUnavailable):
        client_tms.create(ORDER, FP, "r1", key="k-1")
    assert len(seen) == 1  # the open breaker sent nothing
    clock.now += dt.timedelta(seconds=131)  # Retry-After plus the 10 s buffer
    assert client_tms.create(ORDER, FP, "r1", key="k-1").order_id == "ORD-000001"
    assert not breaker.is_open


def test_retries_stop_after_three() -> None:
    clock = Clock()
    client, seen = scripted(*[(502, {})] * 4)
    with pytest.raises(TmsUnavailable):
        tms(client, clock).create(ORDER, FP, "r1", key="k-1")
    assert len(seen) == 4
    assert all(0 <= s <= 8 for s in clock.slept)


def test_the_retry_budget_stops_a_retry_storm() -> None:
    budget = RetryBudget(ratio=0.1, floor=1)
    clock = Clock()
    client, seen = scripted(*[(503, {})] * 10)
    with pytest.raises(TmsUnavailable):
        tms(client, clock, budget=budget).create(ORDER, FP, "r1", key="k-1")
    assert len(seen) == 2  # one try, one retry allowed by the floor, then the budget says no


def test_a_lost_reply_retried_with_the_same_key_creates_one_order() -> None:
    api = TestClient(create_app())
    lost = {"done": False}

    def lose_first_post_reply(response: httpx.Response) -> None:
        if response.request.method == "POST" and not lost["done"]:
            lost["done"] = True
            raise httpx.ReadTimeout("reply lost after the server saved the order")

    api.event_hooks = {"request": [], "response": [lose_first_post_reply]}
    clock = Clock()
    client_tms = HttpTms(api, breaker=CircuitBreaker(clock=clock), sleep=clock.sleep, clock=clock)
    receipt = client_tms.create(ORDER, FP, "tender-1", key=f"create:{FP}")
    assert lost["done"]
    assert [o.order_id for o in client_tms.find(FP)] == [receipt.order_id]


def test_the_same_key_with_a_different_order_is_refused() -> None:
    api = TestClient(create_app())
    clock = Clock()
    client_tms = HttpTms(api, breaker=CircuitBreaker(clock=clock), sleep=clock.sleep, clock=clock)
    client_tms.create(ORDER, FP, "tender-1", key="k-1")
    heavier = ORDER.model_copy(update={"weight_lb": ORDER.weight_lb + 100})
    with pytest.raises(TmsError) as err:
        client_tms.create(heavier, FP, "tender-1", key="k-1")
    assert err.value.status == 422


def test_change_and_cancel_through_the_client() -> None:
    api = TestClient(create_app())
    clock = Clock()
    client_tms = HttpTms(api, breaker=CircuitBreaker(clock=clock), sleep=clock.sleep, clock=clock)
    created = client_tms.create(ORDER, FP, "tender-1", key="k-1")
    changed = client_tms.change(created.order_id, ORDER, "tender-2", key="k-2")
    assert changed.version == 2
    assert client_tms.cancel(created.order_id, "tender-3", key="k-3").status == "cancelled"


def test_the_fingerprint_holds_across_resends_and_changes_but_not_orders() -> None:
    by_id = {c.id: c for c in CASES}
    for case in CASES:
        if case.duplicate_of:
            original = by_id[case.duplicate_of].tender.order
            assert fingerprint(case.tender.order) == fingerprint(original)
    originals = [c.tender.order for c in CASES if c.duplicate_of is None]
    assert len({fingerprint(o) for o in originals}) == len(originals)
    assert all(c.tender.source in Source for c in CASES)


def test_connect_sets_a_timeout_on_every_attempt() -> None:
    from freight_agents.tms_orders.tms import connect

    client_tms = connect("http://tms.test", timeout_s=7.5)
    assert client_tms.client.timeout.read == 7.5
    assert client_tms.breaker is connect("http://tms.test").breaker  # one breaker per service
