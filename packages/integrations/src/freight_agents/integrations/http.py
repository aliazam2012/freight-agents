"""A resilient HTTP layer for calls to outside services (a TMS, a carrier's API).

Layers, outermost first, per the repository's external API resilience standard:
circuit breaker (a 429 freezes every call for the Retry-After window plus a
buffer; nothing is sent while it is open), token bucket, retry with full-jitter
exponential backoff (at most 3 retries, inside a 10% retry budget), and a timeout
on every attempt (set on the client). Writes carry an Idempotency-Key that stays
the same across retries, so a reply lost after the service acted replays that
result rather than repeating the action.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

RETRYABLE = frozenset({408, 409, 500, 502, 503, 504})
LOCKOUT_BUFFER_S = 10.0
# The mock TMS publishes no rate limit; these are this client's own assumptions.
DEFAULT_LOCKOUT_S = 60.0
RATE_PER_S = 5.0
BURST = 5

Clock = Callable[[], dt.datetime]


class HttpResponse(Protocol):
    """The part of a response this client reads; httpx and Starlette's test client both fit."""

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    @property
    def base_url(self) -> Any: ...

    def request(
        self, method: str, url: str, *, json: Any = ..., headers: Any = ..., params: Any = ...
    ) -> HttpResponse: ...


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class HttpError(Exception):
    def __init__(self, status: int, title: str) -> None:
        super().__init__(f"service answered {status}: {title}")
        self.status = status
        self.title = title


class Unavailable(HttpError):
    """The service cannot be reached now: breaker open, rate limited, or retries spent."""


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
            raise Unavailable(503, f"circuit open until {self.open_until:%H:%M:%S}")
        if self.open_until is not None:
            log.warning("circuit breaker reset after its lockout")
            self.open_until = None

    def trip(self, seconds: float) -> None:
        lockout = seconds + LOCKOUT_BUFFER_S
        self.open_until = self.clock() + dt.timedelta(seconds=lockout)
        log.warning("circuit breaker tripped for %.0f seconds", lockout)


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
                log.warning("rate limiter waiting %.1f seconds", wait)
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


def _retry_after(response: HttpResponse) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _title(response: HttpResponse) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        return str(body.get("title") or body.get("detail") or body)
    return str(body)[:200]


class ResilientHttp:
    def __init__(
        self,
        client: HttpClient,
        *,
        service: str = "service",
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
        self.service = service
        self.breaker = breaker or breaker_for(str(client.base_url))
        self.bucket = bucket or TokenBucket(RATE_PER_S, BURST, clock, sleep)
        self.budget = budget or RetryBudget()
        self.retries, self.base_s, self.cap_s = retries, base_s, cap_s
        self.sleep = sleep
        self.rng = rng or random.Random()

    def send(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        key: str | None = None,
        params: dict[str, str] | None = None,
    ) -> HttpResponse:
        self.breaker.check()
        headers = {"Idempotency-Key": f'"{key}"'} if key is not None else {}
        for attempt in range(self.retries + 1):
            self.bucket.acquire()
            self.budget.requests += 1
            wait: float | None = None
            try:
                response = self.client.request(
                    method, url, json=json, headers=headers, params=params
                )
            except httpx.TransportError as exc:
                problem = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 429:
                    self.breaker.trip(_retry_after(response) or DEFAULT_LOCKOUT_S)
                    raise Unavailable(429, "rate limited; circuit opened")
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRYABLE:
                    raise HttpError(response.status_code, _title(response))
                problem, wait = f"HTTP {response.status_code}", _retry_after(response)
            if attempt == self.retries or not self.budget.allow():
                raise Unavailable(
                    503, f"{method} {url} failed after {attempt + 1} tries: {problem}"
                )
            delay = self.rng.uniform(0, min(self.cap_s, self.base_s * 2**attempt))
            if wait is not None:
                delay += wait
            log.warning(
                "%s %s %s attempt %d of %d failed (%s); retrying in %.1f s",
                self.service,
                method,
                url,
                attempt + 1,
                self.retries + 1,
                problem,
                delay,
            )
            self.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover


def http_client(base_url: str, timeout_s: float = 30.0) -> httpx.Client:
    """An httpx client whose timeout applies to every attempt."""
    return httpx.Client(base_url=base_url, timeout=httpx.Timeout(timeout_s))
