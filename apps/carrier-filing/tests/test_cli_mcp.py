import datetime as dt
import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from freight_agents.carrier_filing.cli import main
from freight_agents.carrier_filing.mcp_server import build_filing_server
from freight_agents.claims_intake.workflow import Stores as ClaimsStores
from mcp import Client

from .conftest import FIELDS, Desk, claims_case


def _call(server: Any, name: str, args: dict[str, Any]) -> tuple[bool, Any]:
    async def go() -> tuple[bool, Any]:
        async with Client(server) as client:
            result = await client.call_tool(name, args)
            return bool(result.is_error), json.loads(result.content[0].text)

    return anyio.run(go)


def _names(server: Any) -> set[str]:
    async def go() -> set[str]:
        async with Client(server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    return anyio.run(go)


def test_mcp_reads_claims_deadlines_status_and_rules(world: Desk) -> None:
    world.desk.open_from_claims_case("claim-001", claims_case("Example Freight Lines"))
    server = build_filing_server(world.desk)
    assert _names(server) == {
        "get_claim",
        "list_pending_sends",
        "check_status",
        "claim_deadlines",
        "search_claim_rules",
    }
    error, claim = _call(server, "get_claim", {"case_id": "claim-001"})
    assert not error
    assert claim["state"] == "filed"
    error, due = _call(server, "claim_deadlines", {"case_id": "claim-001"})
    assert due["acknowledgement_due"] == "2026-12-31"
    assert due["disposition_due"] == "2027-03-31"
    world.api.post("/admin/claims/EXFL-C-000001/acknowledge")
    error, status = _call(server, "check_status", {"case_id": "claim-001"})
    assert status["state"] == "acknowledged"
    error, hits = _call(server, "search_claim_rules", {"query": "acknowledge within 30 days"})
    assert any("370" in p["title"] for p in hits["passages"])
    error, _ = _call(server, "get_claim", {"case_id": "nope"})
    assert error


def _handed_off(claims_state: Path, case_id: str, carrier: str) -> None:
    stores = ClaimsStores.at(claims_state)
    engine = stores.engine
    fields = FIELDS.model_copy(update={"carrier": carrier}).model_dump(mode="json")
    engine.open(case_id, {"email": {"sender": "claims@lhg.example.com"}}, actor="test")
    engine.fire(case_id, "triage_claim", actor="test")
    engine.fire(case_id, "extracted", {"fields": fields}, actor="test")
    engine.fire(case_id, "complete", actor="test")
    engine.fire(case_id, "handoff", actor="test")


def test_the_cli_files_handed_off_claims_and_follows_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claims, state = tmp_path / "claims", tmp_path / "filing"
    _handed_off(claims, "claim-101", "Example Freight Lines")
    _handed_off(claims, "claim-102", "Example Truck Lines")
    assert main(["--state", str(state), "from-claims", "--claims-state", str(claims)]) == 0
    out = capsys.readouterr().out
    assert "claim-101" in out
    assert "filed" in out
    assert "claim-102" in out
    assert "ready" in out
    later = (dt.datetime.now(dt.UTC) + dt.timedelta(days=40)).isoformat()
    assert main(["--state", str(state), "tick", "--now", later]) == 0
    assert "claim-101" in capsys.readouterr().out
    assert main(["--state", str(state), "pending"]) == 0
    listing = capsys.readouterr().out
    assert "send_claim_email" in listing
    assert "draft_follow_up" in listing
    # Running the handoff again files nothing new.
    assert main(["--state", str(state), "from-claims", "--claims-state", str(claims)]) == 0
    assert main(["--state", str(state), "show", "claim-101"]) == 0
    assert capsys.readouterr().out.count("filed") >= 1
