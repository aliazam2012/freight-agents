import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from freight_agents.mock_carrier.app import PORTAL_PASSWORD, PORTAL_USER, create_app

SPEC = Path(__file__).resolve().parents[1] / "openapi.json"
CLAIM = {
    "reference": "claim-001",
    "claimant": "Larkspur Home Goods",
    "pro_number": "7741-2209",
    "bol_number": "BOL-55102",
    "claim_type": "damage",
    "description": "4 of 12 chairs broken",
    "amount_usd": 640.0,
    "documents": ["cover.pdf", "photo-1.jpg"],
}


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 12, 1, 15, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def carrier(clock: Clock) -> TestClient:
    return TestClient(create_app(scac="EXFL", clock=clock))


def post(api: TestClient, body: dict[str, Any], key: str = "k-1") -> Any:
    return api.post("/api/claims", json=body, headers={"Idempotency-Key": f'"{key}"'})


def test_api_files_a_claim_once_per_key(carrier: TestClient) -> None:
    first = post(carrier, CLAIM)
    assert first.status_code == 201
    claim = first.json()
    assert claim["claim_number"] == "EXFL-C-000001"
    assert claim["status"] == "received"
    assert claim["received_on"] == "2026-12-01"
    assert post(carrier, CLAIM).json() == claim
    assert post(carrier, CLAIM | {"amount_usd": 1.0}).status_code == 422
    assert carrier.post("/api/claims", json=CLAIM).status_code == 400
    assert carrier.get("/api/claims", params={"reference": "claim-001"}).json() == [claim]
    assert carrier.get(f"/api/claims/{claim['claim_number']}").json() == claim


def test_the_carrier_acknowledges_and_disposes(carrier: TestClient, clock: Clock) -> None:
    number = post(carrier, CLAIM).json()["claim_number"]
    clock.now += dt.timedelta(days=12)
    carrier.post(f"/admin/claims/{number}/acknowledge")
    clock.now += dt.timedelta(days=40)
    carrier.post(f"/admin/claims/{number}/offer", params={"amount": 400})
    claim = carrier.get(f"/api/claims/{number}").json()
    assert claim["acknowledged_on"] == "2026-12-13"
    assert claim["disposition"] == "offered"
    assert claim["disposition_amount"] == 400.0
    assert claim["disposition_on"] == "2027-01-22"


def _login(portal: TestClient) -> None:
    r = portal.post(
        "/portal/login",
        data={"username": PORTAL_USER, "password": PORTAL_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 303


def _form() -> dict[str, str]:
    return {k: str(v) for k, v in CLAIM.items() if k != "documents"}


def test_the_portal_files_a_claim_and_shows_its_number(carrier: TestClient) -> None:
    assert "Sign in" in carrier.get("/portal/claims/new").text  # no session yet
    _login(carrier)
    page = carrier.get("/portal/claims/new")
    assert "name='amount_usd'" in page.text
    upload = [("documents", ("cover.pdf", b"%PDF-1.4", "application/pdf"))]
    done = carrier.post("/portal/claims", data=_form(), files=upload)
    assert done.status_code == 200
    number = re.search(r"Claim number: (EXFL-C-\d+)", done.text)
    assert number is not None
    mine = carrier.get("/portal/claims").text
    assert number.group(1) in mine
    assert "claim-001" in mine


def test_an_expired_portal_session_files_nothing(carrier: TestClient, clock: Clock) -> None:
    _login(carrier)
    clock.now += dt.timedelta(minutes=31)
    r = carrier.post("/portal/claims", data=_form(), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("/portal/login")
    assert carrier.get("/api/claims").json() == []


def test_the_portal_has_no_idempotency_so_a_double_submit_files_twice(carrier: TestClient) -> None:
    _login(carrier)
    carrier.post("/portal/claims", data=_form())
    carrier.post("/portal/claims", data=_form())
    assert len(carrier.get("/api/claims", params={"reference": "claim-001"}).json()) == 2


def test_the_committed_openapi_file_matches_the_app() -> None:
    assert json.loads(SPEC.read_text()) == create_app(scac="EXFL").openapi()
