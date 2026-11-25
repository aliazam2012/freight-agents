import datetime as dt
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from freight_agents.carrier_filing.channels import ApiChannel, EmailChannel, PortalChannel
from freight_agents.carrier_filing.desk import FilingDesk, Stores
from freight_agents.carrier_filing.domain import carrier_for
from freight_agents.claims_intake.domain import ClaimFields
from freight_agents.integrations.http import CircuitBreaker
from freight_agents.mock_carrier.app import PORTAL_PASSWORD, PORTAL_USER, create_app


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 12, 1, 15, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


class Served:
    def __init__(self, app: FastAPI, url: str) -> None:
        self.app, self.url = app, url


def serve(app: FastAPI) -> Iterator[Served]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the mock carrier did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield Served(app, f"http://127.0.0.1:{port}")
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def portal(clock: Clock) -> Iterator[Served]:
    yield from serve(create_app(scac="EXME", clock=clock))


@pytest.fixture
def redesigned_portal(clock: Clock) -> Iterator[Served]:
    yield from serve(create_app(scac="EXME", clock=clock, portal_without=("amount_usd",)))


FIELDS = ClaimFields(
    pro_number="7741-2209",
    bol_number="BOL-55102",
    carrier="Example Freight Lines",
    ship_date=dt.date(2026, 11, 2),
    delivery_date=dt.date(2026, 11, 9),
    commodity="dining chairs",
    claim_type="damage",
    damage_description="4 of 12 chairs arrived with broken legs",
    claimed_amount_usd=640.0,
    claimant_name="Larkspur Home Goods",
    claimant_email="claims@lhg.example.com",
    photo_count=1,
)


def claims_case(carrier: str, **change: Any) -> dict[str, Any]:
    fields = FIELDS.model_copy(update={"carrier": carrier, **change})
    return {"fields": fields.model_dump(mode="json")}


class Desk:
    def __init__(self, root: Path, clock: Clock, portal: Served | None = None) -> None:
        self.clock = clock
        self.api = TestClient(create_app(scac="EXFL", clock=clock))
        self.stores = Stores.at(root / "state", clock)
        channels: dict[str, Any] = {
            "EXFL": ApiChannel(
                self.api,
                carrier_for("EXFL"),
                clock=clock,
                breaker=CircuitBreaker(clock=clock),
                sleep=lambda s: None,
            ),
            "EXTL": EmailChannel(
                carrier_for("EXTL"),
                self.stores.transport,
                sender="claims@lhg.example.com",
                outbox=root / "state" / "outbox",
                clock=clock,
            ),
        }
        if portal is not None:
            channels["EXME"] = PortalChannel(
                carrier_for("EXME"), PORTAL_USER, PORTAL_PASSWORD, base_url=portal.url
            )
        self.desk = FilingDesk(self.stores, channels, clock=clock)

    def pending(self) -> list[Any]:
        return self.stores.approvals.pending()

    def sent_to(self) -> list[str]:
        from email import message_from_bytes

        outbox = self.stores.transport.directory  # type: ignore[attr-defined]
        return [message_from_bytes(p.read_bytes())["To"] for p in sorted(outbox.glob("*.eml"))]


@pytest.fixture
def world(tmp_path: Path, clock: Clock) -> Desk:
    return Desk(tmp_path, clock)
