"""freight-filing: file handed-off claims, run deadline reminders, approve sends, show a claim."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from freight_agents.carrier_filing.channels import ApiChannel, EmailChannel, PortalChannel
from freight_agents.carrier_filing.desk import FilingDesk, Stores
from freight_agents.carrier_filing.domain import carrier_for
from freight_agents.integrations.http import CircuitBreaker, TokenBucket
from freight_agents.llm import Model

DEFAULT_STATE = Path("var/filing")
DEFAULT_CLAIMS = Path("var/claims")
CLAIMANT = "claims@lhg.example.com"


class LocalCarriers(Mapping[str, Any]):
    """The made-up carriers in this process; the portal is served only when first needed."""

    def __init__(self, state: Path, stores: Stores, portal_url: str | None) -> None:
        self.state, self.stores, self.portal_url = state, stores, portal_url
        self._made: dict[str, Any] = {}
        self._servers: list[Any] = []

    def __getitem__(self, scac: str) -> Any:
        if scac not in self._made:
            self._made[scac] = self._make(scac)
        return self._made[scac]

    def __iter__(self) -> Iterator[str]:
        return iter(["EXFL", "EXME", "EXTL"])

    def __len__(self) -> int:
        return 3

    def _make(self, scac: str) -> Any:
        import time

        from fastapi.testclient import TestClient
        from freight_agents.mock_carrier.app import PORTAL_PASSWORD, PORTAL_USER, create_app

        carrier = carrier_for(scac)
        if carrier.channel == "api":
            client = TestClient(create_app(scac="EXFL", db=self.state / "exfl.sqlite3"))
            breaker = CircuitBreaker()
            bucket = TokenBucket(1_000.0, 1_000, breaker.clock, time.sleep)
            return ApiChannel(client, carrier, breaker=breaker, bucket=bucket)
        if carrier.channel == "portal":
            url = self.portal_url or self._serve(
                create_app(scac="EXME", db=self.state / "exme.sqlite3")
            )
            return PortalChannel(carrier, PORTAL_USER, PORTAL_PASSWORD, base_url=url)
        return EmailChannel(
            carrier, self.stores.transport, sender=CLAIMANT, outbox=self.state / "outbox"
        )

    def _serve(self, app: Any) -> str:
        import threading
        import time

        import uvicorn

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.02)
        self._servers.append(server)
        return f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"

    def close(self) -> None:
        for server in self._servers:
            server.should_exit = True


def _handed_off(claims_state: Path) -> list[tuple[str, dict[str, Any]]]:
    from freight_agents.claims_intake.workflow import Stores as ClaimsStores

    engine = ClaimsStores.at(claims_state).engine
    out = []
    for case_id in engine.store.case_ids():
        case = engine.view(case_id)
        if case.state == "handed_off":
            out.append((case_id, case.data))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="freight-filing")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--portal-url", help="a running carrier portal; omit for the local mock")
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("from-claims", help="file every claim claims-intake handed off")
    pull.add_argument("--claims-state", type=Path, default=DEFAULT_CLAIMS)
    tick = commands.add_parser("tick", help="fire due 370 reminders and draft follow-ups")
    tick.add_argument("--now", help="ISO time to run the reminders at; default now")
    check = commands.add_parser("check", help="ask the carrier for a claim's status")
    check.add_argument("case_id")
    commands.add_parser("pending", help="list sends waiting for approval")
    approve = commands.add_parser("approve", help="approve one send")
    approve.add_argument("approval_id")
    approve.add_argument("--by", required=True)
    show = commands.add_parser("show", help="print a claim and its history")
    show.add_argument("case_id")
    commands.add_parser("mcp", help="serve the read tools over MCP on stdio")
    evaluate = commands.add_parser("eval", help="play every scenario and grade it")
    evaluate.add_argument("--reports", type=Path, default=Path("apps/carrier-filing/evals/reports"))
    evaluate.add_argument("--day", default=dt.date.today().isoformat())
    evaluate.add_argument(
        "--mode", choices=["reference", "recorded", "record"], default="reference"
    )
    evaluate.add_argument(
        "--cassettes", type=Path, default=Path("apps/carrier-filing/evals/cassettes")
    )
    evaluate.add_argument("--model-name", default="claude-opus-5-5")
    evaluate.add_argument("--max-usd", type=float, default=0.0, help="record: the approved cap")
    evaluate.add_argument("--limit", type=int, help="record: only the first N scenarios")
    args = parser.parse_args(argv)
    if args.command == "eval":
        return _evaluate(args)

    at = dt.datetime.fromisoformat(args.now) if getattr(args, "now", None) else None
    stores = Stores.at(args.state)
    carriers = LocalCarriers(args.state, stores, args.portal_url)
    desk = FilingDesk(
        stores, carriers, clock=(lambda: at) if at else lambda: dt.datetime.now(dt.UTC)
    )
    try:
        return _run(args, desk, stores)
    finally:
        carriers.close()


def _run(args: argparse.Namespace, desk: FilingDesk, stores: Stores) -> int:
    if args.command == "from-claims":
        for case_id, data in _handed_off(args.claims_state):
            try:
                case = desk.open_from_claims_case(case_id, data)
            except (KeyError, ValueError) as exc:
                print(f"{case_id:<24} not filed: {exc}")
                continue
            print(f"{case_id:<24} {case.state}")
        return 0
    if args.command == "tick":
        for case in desk.tick():
            print(f"{case.case_id:<24} follow-up drafted ({case.data.get('followup_rule')})")
        return 0
    if args.command == "check":
        print(desk.check(args.case_id).state)
        return 0
    if args.command == "pending":
        for item in stores.approvals.pending():
            print(f"{item.id}  {item.case_id}  {item.tool}  to {item.args.get('to')}")
            print(f"    {item.args.get('subject')}")
        return 0
    if args.command == "approve":
        print(desk.approve(args.approval_id, args.by).state)
        return 0
    if args.command == "mcp":
        return _serve(desk)
    case = stores.engine.view(args.case_id)
    print(f"{case.case_id}  state: {case.state}")
    for event in case.history:
        detail = event.payload.get("event") or ", ".join(sorted(event.payload.get("data", {})))
        print(f"  {event.seq:>3}  {event.at.isoformat()}  {event.type:<16} {detail}")
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    from freight_agents.carrier_filing.evaluation import (
        FLOORS,
        record,
        run,
        run_recorded,
        write_report,
    )
    from freight_agents.evals.recording import StaleCassette

    if args.mode == "record":
        from freight_agents.llm.anthropic_adapter import AnthropicModel

        def live(case_id: str) -> Model:
            return AnthropicModel(model=args.model_name, effort="low")

        return record(args.cassettes, live, args.max_usd, args.limit).code
    try:
        result = (
            run() if args.mode == "reference" else run_recorded(args.cassettes, args.model_name)
        )
    except StaleCassette as exc:
        print(f"FAIL {exc}")
        return 2
    model = None if args.mode == "reference" else args.model_name
    path = write_report(result, args.reports, args.day, args.mode, model)
    for name, value in result.metrics.items():
        print(f"{name}: {value:.2f}")
    failures = result.failures(FLOORS)
    print(f"gate: {'passed' if not failures else 'failed: ' + '; '.join(failures)}")
    print(f"report: {path}")
    return 1 if failures else 0


def _serve(desk: FilingDesk) -> int:
    import anyio
    from freight_agents.carrier_filing.mcp_server import build_filing_server
    from mcp.server.stdio import stdio_server

    server = build_filing_server(desk)

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
