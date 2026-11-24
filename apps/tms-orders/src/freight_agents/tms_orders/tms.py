"""The TMS order client: exactly-once writes over an unreliable network.

The resilience (breaker, rate limit, retries, budget, per-attempt timeout, one
Idempotency-Key across retries) lives in the shared integrations http module; this
module adds the TMS calls and the duplicate fingerprint, which names a load the way
a planner would: shipper, the shipper's reference, pickup date, and origin and final
destination ZIP codes. A resent tender, a change and a cancellation of one load
share it.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from freight_agents.integrations.http import (
    CircuitBreaker,
    HttpClient,
    HttpError,
    ResilientHttp,
    RetryBudget,
    TokenBucket,
    Unavailable,
    breaker_for,
    http_client,
)
from freight_agents.tms_orders.domain import Order
from pydantic import BaseModel

__all__ = [
    "CircuitBreaker",
    "HttpClient",
    "HttpTms",
    "Receipt",
    "RetryBudget",
    "TmsError",
    "TmsUnavailable",
    "TokenBucket",
    "breaker_for",
    "connect",
    "fingerprint",
]

TmsError = HttpError
TmsUnavailable = Unavailable


class Receipt(BaseModel):
    order_id: str
    status: Literal["open", "cancelled"]
    version: int
    fingerprint: str
    tender_reference: str
    order: dict[str, Any]


def fingerprint(order: Order) -> str:
    pickup = order.stops[0]
    parts = [
        " ".join(order.shipper.name.lower().split()),
        order.shipper_reference.strip().upper(),
        pickup.window_start.date().isoformat(),
        pickup.party.zip[:5],
        order.stops[-1].party.zip[:5],
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


class HttpTms(ResilientHttp):
    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        return self.send(method, url, **kwargs)

    def create(self, order: Order, print_: str, tender_reference: str, key: str) -> Receipt:
        body = {
            "fingerprint": print_,
            "tender_reference": tender_reference,
            "order": order.model_dump(mode="json"),
        }
        return Receipt.model_validate(self._send("POST", "/orders", json=body, key=key).json())

    def find(self, print_: str) -> list[Receipt]:
        found = self._send("GET", "/orders", params={"fingerprint": print_}).json()
        return [Receipt.model_validate(item) for item in found]

    def find_all(self) -> list[Receipt]:
        return [Receipt.model_validate(item) for item in self._send("GET", "/orders").json()]

    def change(self, order_id: str, order: Order, tender_reference: str, key: str) -> Receipt:
        body = {
            "action": "change",
            "tender_reference": tender_reference,
            "order": order.model_dump(mode="json"),
        }
        return Receipt.model_validate(
            self._send("PATCH", f"/orders/{order_id}", json=body, key=key).json()
        )

    def cancel(self, order_id: str, tender_reference: str, key: str) -> Receipt:
        body = {"action": "cancel", "tender_reference": tender_reference, "order": None}
        return Receipt.model_validate(
            self._send("PATCH", f"/orders/{order_id}", json=body, key=key).json()
        )


def connect(base_url: str, timeout_s: float = 30.0) -> HttpTms:
    """A client for a TMS at `base_url`; the timeout applies to every attempt."""
    return HttpTms(http_client(base_url, timeout_s), service="TMS")
