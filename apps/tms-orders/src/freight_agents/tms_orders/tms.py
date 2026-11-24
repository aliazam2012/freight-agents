"""The TMS order client: exactly-once writes over an unreliable network.

Layers, outermost first, per the repository's external API resilience standard:
circuit breaker (a 429 freezes every call for the Retry-After window plus a
buffer; nothing is sent while it is open), token bucket, retry with full-jitter
exponential backoff (at most 3 retries, inside a 10% retry budget), and a timeout
on every attempt. Writes carry an Idempotency-Key that stays the same across
retries, so a reply lost after the TMS saved the order replays that order rather
than creating a second one.

The duplicate fingerprint names a load the way a planner would: shipper, the
shipper's reference, pickup date, and origin and final destination ZIP codes. A
resent tender, a change and a cancellation of one load share it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import random
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx
from freight_agents.tms_orders.domain import Order
from pydantic import BaseModel

log = logging.getLogger(__name__)

RETRYABLE = frozenset({408, 409, 500, 502, 503, 504})
LOCKOUT_BUFFER_S = 10.0
# The mock TMS publishes no rate limit; these are this client's own assumptions.
DEFAULT_LOCKOUT_S = 60.0
RATE_PER_S = 5.0
BURST = 5

Clock = Callable[[], dt.datetime]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class TmsError(Exception):
    def __init__(self, status: int, title: str) -> None:
        super().__init__(f"TMS answered {status}: {title}")
        self.status = status
        self.title = title


class TmsUnavailable(TmsError):
    """The TMS cannot be reached now: breaker open, rate limited, or retries spent."""


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


class CircuitBreaker:
    """Open after a 429 for the server's Retry-After window plus a buffer; closed otherwise."""

    def __init__(self, clock: Clock = _now) -> None:
        self.clock = clock
        self.open_until: dt.datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.open_until is not None and self.clock() < self.open_until

    def check(self) -> None:
        if self.is_open:
            raise TmsUnavailable(503, f"circuit open until {self.open_until:%H:%M:%S}")
        if self.open_until is not None:
            log.warning("TMS circuit breaker reset after its lockout")
            self.open_until = None

    def trip(self, seconds: float) -> None:
        lockout = seconds + LOCKOUT_BUFFER_S
        self.open_until = self.clock() + dt.timedelta(seconds=lockout)
        log.warning("TMS circuit breaker tripped for %.0f seconds", lockout)


_BREAKERS: dict[str, CircuitBreaker] = {}


def breaker_for(service: str) -> CircuitBreaker:
    """One breaker per service, shared by every client of it in this process."""
    return _BREAKERS.setdefault(service, CircuitBreaker())


class TokenBucket:
    def __init__(self, rate: float, capacity: int, clock: Clock, sleep: Callable[[float], None]):
        self.rate, self.capacity, self.clock, self.sleep = rate, capacity, clock, sleep
        self.tokens = float(capacity)
        self.at = clock()

    def acquire(self) -> None:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.at).total_seconds() * self.rate)
        self.at = now
        if self.tokens < 1:
            wait = (1 - self.tokens) / self.rate
            if wait > 1:
                log.warning("TMS rate limiter waiting %.1f seconds", wait)
            self.sleep(wait)
            self.tokens, self.at = 1.0, self.clock()
        self.tokens -= 1


class RetryBudget:
    """Retries may not exceed `floor` plus `ratio` of all requests this client made."""

    def __init__(self, ratio: float = 0.1, floor: int = 3) -> None:
        self.ratio, self.floor = ratio, floor
        self.requests = 0
        self.retries = 0

    def allow(self) -> bool:
        if self.retries + 1 <= self.floor + self.ratio * self.requests:
            self.retries += 1
            return True
        return False


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _title(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        return str(body.get("title") or body.get("detail") or body)
    return str(body)[:200]


class HttpTms:
    def __init__(
        self,
        client: httpx.Client,
        *,
        breaker: CircuitBreaker | None = None,
        bucket: TokenBucket | None = None,
        budget: RetryBudget | None = None,
        retries: int = 3,
        base_s: float = 2.0,
        cap_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Clock = _now,
        rng: random.Random | None = None,
    ) -> None:
        self.client = client
        self.breaker = breaker or breaker_for(str(client.base_url))
        self.bucket = bucket or TokenBucket(RATE_PER_S, BURST, clock, sleep)
        self.budget = budget or RetryBudget()
        self.retries, self.base_s, self.cap_s = retries, base_s, cap_s
        self.sleep = sleep
        self.rng = rng or random.Random()

    def _send(self, method: str, url: str, *, json: Any = None, key: str | None = None,
              params: dict[str, str] | None = None) -> httpx.Response:  # fmt: skip
        self.breaker.check()
        headers = {"Idempotency-Key": f'"{key}"'} if key is not None else {}
        for attempt in range(self.retries + 1):
            self.bucket.acquire()
            self.budget.requests += 1
            wait: float | None = None
            try:
                response = self.client.request(method, url, json=json, headers=headers,
                                               params=params)  # fmt: skip
            except httpx.TransportError as exc:
                problem = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 429:
                    self.breaker.trip(_retry_after(response) or DEFAULT_LOCKOUT_S)
                    raise TmsUnavailable(429, "rate limited; circuit opened")
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRYABLE:
                    raise TmsError(response.status_code, _title(response))
                problem, wait = f"HTTP {response.status_code}", _retry_after(response)
            if attempt == self.retries or not self.budget.allow():
                raise TmsUnavailable(503, f"{method} {url} failed after {attempt + 1} tries: "
                                     f"{problem}")  # fmt: skip
            delay = self.rng.uniform(0, min(self.cap_s, self.base_s * 2**attempt))
            if wait is not None:
                delay += wait
            log.warning("TMS %s %s attempt %d of %d failed (%s); retrying in %.1f s", method,
                        url, attempt + 1, self.retries + 1, problem, delay)  # fmt: skip
            self.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def create(self, order: Order, print_: str, tender_reference: str, key: str) -> Receipt:
        body = {"fingerprint": print_, "tender_reference": tender_reference,
                "order": order.model_dump(mode="json")}  # fmt: skip
        return Receipt.model_validate(self._send("POST", "/orders", json=body, key=key).json())

    def find(self, print_: str) -> list[Receipt]:
        found = self._send("GET", "/orders", params={"fingerprint": print_}).json()
        return [Receipt.model_validate(item) for item in found]

    def change(self, order_id: str, order: Order, tender_reference: str, key: str) -> Receipt:
        body = {"action": "change", "tender_reference": tender_reference,
                "order": order.model_dump(mode="json")}  # fmt: skip
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
    return HttpTms(httpx.Client(base_url=base_url, timeout=httpx.Timeout(timeout_s)))
