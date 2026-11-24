import datetime as dt
from email import message_from_bytes
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from freight_agents.carrier_filing.channels import (
    ApiChannel,
    EmailChannel,
    PortalChannel,
    PortalError,
)
from freight_agents.carrier_filing.domain import carrier_for, from_claims_case
from freight_agents.claims_intake.domain import ClaimFields
from freight_agents.integrations.http import CircuitBreaker
from freight_agents.integrations.transport import FileTransport
from freight_agents.mock_carrier.app import PORTAL_PASSWORD, PORTAL_USER, create_app

from .conftest import Clock, Served

FIELDS = ClaimFields(
    pro_number="7741-2209", bol_number="BOL-55102", carrier="Example Freight Lines",
    ship_date=dt.date(2026, 11, 2), delivery_date=dt.date(2026, 11, 9),
    commodity="dining chairs", claim_type="damage",
    damage_description="4 of 12 chairs arrived with broken legs", claimed_amount_usd=640.0,
    claimant_name="Larkspur Home Goods", claimant_email="claims@lhg.example.com", photo_count=1,
)  # fmt: skip


def packet(carrier: str, reference: str = "claim-001") -> Any:
    fields = FIELDS.model_copy(update={"carrier": carrier})
    return from_claims_case(reference, {"fields": fields.model_dump(mode="json")})


def api_channel(client: Any, clock: Clock) -> ApiChannel:
    return ApiChannel(client, carrier_for("Example Freight Lines"), clock=clock,
                      breaker=CircuitBreaker(clock=clock), sleep=lambda s: None)  # fmt: skip


def test_the_api_files_once_and_a_rerun_finds_the_filing(clock: Clock) -> None:
    carrier = TestClient(create_app(scac="EXFL", clock=clock))
    receipt = api_channel(carrier, clock).file(packet("Example Freight Lines"), [])
    assert receipt.carrier_claim_number == "EXFL-C-000001"
    assert receipt.received_on == dt.date(2026, 12, 1)
    # A run that crashed before saving the receipt files again: the carrier has it already.
    again = api_channel(carrier, clock).file(packet("Example Freight Lines"), [])
    assert again == receipt
    assert len(carrier.get("/api/claims").json()) == 1


def test_an_api_reply_lost_in_flight_is_retried_with_the_same_key(clock: Clock) -> None:
    carrier = TestClient(create_app(scac="EXFL", clock=clock))
    lost = {"done": False}

    def lose(response: httpx.Response) -> None:
        if response.request.method == "POST" and not lost["done"]:
            lost["done"] = True
            raise httpx.ReadTimeout("reply lost after the carrier saved the claim")

    carrier.event_hooks = {"request": [], "response": [lose]}
    api_channel(carrier, clock).file(packet("Example Freight Lines"), [])
    assert lost["done"]
    assert len(carrier.get("/api/claims").json()) == 1


def test_api_status_follows_the_carrier(clock: Clock) -> None:
    carrier = TestClient(create_app(scac="EXFL", clock=clock))
    channel = api_channel(carrier, clock)
    receipt = channel.file(packet("Example Freight Lines"), [])
    clock.now += dt.timedelta(days=9)
    carrier.post(f"/admin/claims/{receipt.carrier_claim_number}/acknowledge")
    status = channel.status(receipt)
    assert status is not None
    assert status.acknowledged_on == dt.date(2026, 12, 10)
    assert status.disposition is None


def portal_channel(served: Served, **kw: Any) -> PortalChannel:
    return PortalChannel(carrier_for("Example Motor Express"), PORTAL_USER, PORTAL_PASSWORD,
                         base_url=served.url, **kw)  # fmt: skip


def claims_on(served: Served) -> list[Any]:
    return served.app.state.store.find(None)  # type: ignore[no-any-return]


def test_the_portal_files_once_and_a_rerun_finds_the_filing(portal: Served,
                                                           tmp_path: Path) -> None:  # fmt: skip
    cover = tmp_path / "cover.pdf"
    cover.write_bytes(b"%PDF-1.4 claim")
    receipt = portal_channel(portal).file(packet("Example Motor Express"), [cover])
    assert receipt.carrier_claim_number.startswith("EXME-C-")
    assert receipt.channel == "portal"
    assert receipt.received_on == dt.date(2026, 12, 1)
    again = portal_channel(portal).file(packet("Example Motor Express"), [cover])
    assert again.carrier_claim_number == receipt.carrier_claim_number
    (stored,) = claims_on(portal)
    assert stored.claim.documents == ["cover.pdf"]


def test_a_session_that_expires_mid_form_files_nothing(portal: Served, clock: Clock) -> None:
    def expire() -> None:
        clock.now += dt.timedelta(minutes=31)

    with pytest.raises(PortalError, match="session"):
        portal_channel(portal, on_form_filled=expire).file(packet("Example Motor Express"), [])
    assert claims_on(portal) == []
    portal_channel(portal).file(packet("Example Motor Express"), [])
    assert len(claims_on(portal)) == 1


def test_a_form_missing_a_field_files_nothing(redesigned_portal: Served) -> None:
    with pytest.raises(PortalError, match="amount_usd"):
        portal_channel(redesigned_portal).file(packet("Example Motor Express"), [])
    assert claims_on(redesigned_portal) == []


def test_email_files_once_and_finds_what_it_sent(tmp_path: Path, clock: Clock) -> None:
    transport = FileTransport(tmp_path / "outbox")
    channel = EmailChannel(carrier_for("Example Truck Lines"), transport,
                           sender="claims@lhg.example.com", outbox=tmp_path / "outbox",
                           clock=clock)  # fmt: skip
    receipt = channel.file(packet("Example Truck Lines"), [])
    assert receipt.carrier_claim_number.startswith("pending:")
    (sent,) = list((tmp_path / "outbox").glob("*.eml"))
    message = message_from_bytes(sent.read_bytes())
    assert message["To"] == "claims@extl.example.com"
    assert "claim-001" in message["Subject"]
    assert "49 CFR 370.3" in message.get_payload()
    assert channel.find("claim-001") == receipt
    assert channel.file(packet("Example Truck Lines"), []) == receipt
    assert len(list((tmp_path / "outbox").glob("*.eml"))) == 1
