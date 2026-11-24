import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from freight_agents.tms_orders.cli import main
from freight_agents.tms_orders.fixtures import write_fixtures
from freight_agents.tms_orders.mcp_server import build_orders_server
from mcp import Client

from .conftest import World


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


def test_mcp_offers_reads_and_rule_search_only(tmp_path: Path) -> None:
    world = World(tmp_path)
    case = world.intake.process(world.path("edi-01"))
    server = build_orders_server(world.intake)
    assert _names(server) == {"get_case", "list_pending_replies", "search_order_rules"}
    error, got = _call(server, "get_case", {"case_id": case.case_id})
    assert not error
    assert got["state"] == "confirmation_pending"
    assert got["tender_id"] == world.gold["edi-01"]["tender"]["order"]["tender_id"]
    error, pending = _call(server, "list_pending_replies", {})
    assert [p["case_id"] for p in pending["replies"]] == [case.case_id]
    error, hits = _call(server, "search_order_rules", {"query": "placard 1,001 pounds"})
    assert not error
    assert any("172.504" in h["title"] for h in hits["passages"])
    error, _ = _call(server, "get_case", {"case_id": "nope"})
    assert error


def test_the_cli_runs_an_inbox_and_a_person_approves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox, state = tmp_path / "tenders", tmp_path / "state"
    write_fixtures(inbox)
    assert main(["--state", str(state), "run", "--inbox", str(inbox)]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") >= 36
    assert "confirmation_pending" in out
    assert "decline_pending" in out
    assert main(["--state", str(state), "pending"]) == 0
    first = capsys.readouterr().out.split()[0]
    assert main(["--state", str(state), "approve", first, "--by", "dana"]) == 0
    assert capsys.readouterr().out.split()[-1] in ("confirmed", "declined")
    # A second run over the same inbox does no new work.
    assert main(["--state", str(state), "run", "--inbox", str(inbox)]) == 0
    again = capsys.readouterr().out
    assert again.count("orders in the TMS") == 1


def test_the_eval_command_writes_a_report(tmp_path: Path) -> None:
    inbox = tmp_path / "tenders"
    write_fixtures(inbox)
    args = ["eval", "--inbox", str(inbox), "--reports", str(tmp_path / "r"), "--day", "2026-11-24"]
    assert main(args) == 0
    assert (tmp_path / "r" / "2026-11-24-reference.md").exists()
