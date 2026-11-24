"""freight-orders: run an inbox of tenders, review cases, approve replies, show a case."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from freight_agents.llm import Model

from .tms import CircuitBreaker, HttpTms, TokenBucket, connect
from .workflow import ModelFor, OrdersIntake, Stores, load_locations, reference_models

DEFAULT_STATE = Path("var/orders")
DEFAULT_INBOX = Path("data/tenders")
FOLDERS = ("edi", "pdf", "email")


def _tms(state: Path, url: str | None) -> HttpTms:
    if url:
        return connect(url)
    # Local mode: the mock TMS in this process, its orders kept next to the case state.
    from fastapi.testclient import TestClient
    from freight_agents.mock_tms.app import create_app

    state.mkdir(parents=True, exist_ok=True)
    breaker = CircuitBreaker()
    # In-process, there is no service to protect: the rate limit applies to a real TMS only.
    bucket = TokenBucket(1_000.0, 1_000, breaker.clock, time.sleep)
    client = TestClient(create_app(db=state / "tms.sqlite3"))
    return HttpTms(client, breaker=breaker, bucket=bucket)


def _models(kind: str, name: str | None, inbox: Path) -> ModelFor:
    if kind == "reference":
        return reference_models(inbox / "gold.jsonl")
    model: Model
    if kind == "anthropic":
        from freight_agents.llm.anthropic_adapter import AnthropicModel

        model = AnthropicModel(model=name) if name else AnthropicModel()
    else:
        if not name:
            raise SystemExit("--model openai needs --model-name")
        from freight_agents.llm.openai_adapter import OpenAIModel

        model = OpenAIModel(model=name)
    return lambda path: model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="freight-orders")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state directory")
    parser.add_argument("--tms-url", help="a running TMS; omit for the in-process mock")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="process every tender in an inbox folder")
    run.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    run.add_argument("--model", choices=["reference", "anthropic", "openai"], default="reference")
    run.add_argument("--model-name")

    commands.add_parser("pending", help="list replies waiting for approval")
    approve = commands.add_parser("approve", help="approve one reply and send it")
    approve.add_argument("approval_id")
    approve.add_argument("--by", required=True)
    review = commands.add_parser("review", help="decide a case waiting for a person")
    review.add_argument("case_id")
    review.add_argument("decision", choices=["submit", "decline"])
    review.add_argument("--by", required=True)
    show = commands.add_parser("show", help="print a case and its history")
    show.add_argument("case_id")
    commands.add_parser("mcp", help="serve the read tools over MCP on stdio")

    args = parser.parse_args(argv)
    inbox: Path = getattr(args, "inbox", DEFAULT_INBOX)
    stores = Stores.at(args.state)
    locations = load_locations(inbox / "locations.json")
    models = _models(getattr(args, "model", "reference"), getattr(args, "model_name", None), inbox)
    intake = OrdersIntake(stores, _tms(args.state, args.tms_url), models, locations)

    if args.command == "run":
        for folder in FOLDERS:
            for path in sorted((inbox / folder).glob("*")):
                case = intake.process(path)
                print(f"{case.case_id:<48} {case.state}")
        print(f"{len(intake.tms.find_all())} orders in the TMS")
        return 0
    if args.command == "pending":
        for item in stores.approvals.pending():
            print(f"{item.id}  {item.case_id}  to {item.args.get('to')}")
            print(f"    {item.args.get('subject')}")
        return 0
    if args.command == "approve":
        print(intake.approve(args.approval_id, approver=args.by).state)
        return 0
    if args.command == "review":
        print(intake.review(args.case_id, args.decision, by=args.by).state)
        return 0
    if args.command == "mcp":
        return _serve(intake)
    case = stores.engine.view(args.case_id)
    print(f"{case.case_id}  state: {case.state}")
    for event in case.history:
        detail = event.payload.get("event") or ", ".join(sorted(event.payload.get("data", {})))
        print(
            f"  {event.seq:>3}  {event.at.isoformat()}  {event.type:<12} {detail}  ({event.actor})"
        )
    return 0


def _serve(intake: OrdersIntake) -> int:
    import anyio
    from mcp.server.stdio import stdio_server

    from .mcp_server import build_orders_server

    server = build_orders_server(intake)

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
