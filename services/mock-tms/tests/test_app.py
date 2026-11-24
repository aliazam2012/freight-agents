import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from freight_agents.mock_tms.app import KEY_TTL, OrderIn, create_app

SPEC = Path(__file__).resolve().parents[1] / "openapi.json"
BODY = {"fingerprint": "fp-1", "tender_reference": "ratecon-001.pdf",
        "order": {"tender_id": "LHG-104201", "weight_lb": 21000}}  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 12, 1, 9, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def api(clock: Clock) -> TestClient:
    return TestClient(create_app(clock=clock))


def post(api: TestClient, body: dict[str, Any], key: str | None = "k-1") -> Any:
    headers = {"Idempotency-Key": f'"{key}"'} if key is not None else {}
    return api.post("/orders", json=body, headers=headers)


def test_create_then_read(api: TestClient) -> None:
    r = post(api, BODY)
    assert r.status_code == 201
    order = r.json()
    assert order["order_id"] == "ORD-000001"
    assert order["status"] == "open"
    assert api.get(f"/orders/{order['order_id']}").json() == order
    assert api.get("/orders", params={"fingerprint": "fp-1"}).json() == [order]
    assert api.get("/orders", params={"fingerprint": "fp-2"}).json() == []


def test_a_retry_with_the_same_key_and_body_replays_the_first_answer(api: TestClient) -> None:
    first = post(api, BODY)
    again = post(api, BODY)
    assert again.status_code == 201
    assert again.json() == first.json()
    assert len(api.get("/orders").json()) == 1


def test_key_errors_follow_the_idempotency_key_draft(api: TestClient) -> None:
    missing = post(api, BODY, key=None)
    assert missing.status_code == 400
    assert missing.headers["content-type"].startswith("application/problem+json")
    unquoted = api.post("/orders", json=BODY, headers={"Idempotency-Key": "k-1"})
    assert unquoted.status_code == 400
    post(api, BODY)
    reused = post(api, BODY | {"fingerprint": "fp-other"})
    assert reused.status_code == 422
    assert reused.json()["status"] == 422


def test_a_request_still_running_with_the_key_is_a_conflict(api: TestClient) -> None:
    store = api.app.state.store  # type: ignore[attr-defined]
    store.begin("k-busy", "POST /orders", OrderIn.model_validate(BODY).model_dump_json())
    assert post(api, BODY, key="k-busy").status_code == 409


def test_keys_expire_after_the_published_window(api: TestClient, clock: Clock) -> None:
    post(api, BODY)
    clock.now += KEY_TTL + dt.timedelta(minutes=1)
    later = post(api, BODY | {"fingerprint": "fp-2"})
    assert later.status_code == 201
    assert later.json()["order_id"] == "ORD-000002"


def test_change_and_cancel(api: TestClient, clock: Clock) -> None:
    order_id = post(api, BODY).json()["order_id"]
    clock.now += dt.timedelta(hours=1)
    change = {"action": "change", "tender_reference": "ratecon-002.pdf",
              "order": BODY["order"] | {"weight_lb": 22000}}  # fmt: skip
    changed = api.patch(f"/orders/{order_id}", json=change, headers={"Idempotency-Key": '"k-2"'})
    assert changed.status_code == 200
    assert changed.json()["order"]["weight_lb"] == 22000
    assert changed.json()["version"] == 2
    cancel = {"action": "cancel", "tender_reference": "ratecon-003.pdf", "order": None}
    gone = api.patch(f"/orders/{order_id}", json=cancel, headers={"Idempotency-Key": '"k-3"'})
    assert gone.json()["status"] == "cancelled"
    late = api.patch(f"/orders/{order_id}", json=change, headers={"Idempotency-Key": '"k-4"'})
    assert late.status_code == 422
    assert api.patch("/orders/ORD-999999", json=cancel,
                     headers={"Idempotency-Key": '"k-5"'}).status_code == 404  # fmt: skip


def test_the_committed_openapi_file_matches_the_app() -> None:
    assert json.loads(SPEC.read_text()) == create_app().openapi()
