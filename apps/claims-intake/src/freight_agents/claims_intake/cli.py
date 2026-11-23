"""freight-claims: run the inbox, review pending sends, approve one, show a case."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from freight_agents.integrations.email import DirectoryInbox
from freight_agents.integrations.tms import FixtureTms
from freight_agents.llm import Model, ReplayModel

from .workflow import ClaimsIntake, Stores

DEFAULT_STATE = Path("var/claims")


def _model(kind: str, name: str | None, cassette: Path | None) -> Model:
    if kind == "replay":
        if cassette is None or name is None:
            raise SystemExit("--model replay needs --cassette and --model-name")
        return ReplayModel(cassette, name=name)
    if kind == "anthropic":
        from freight_agents.llm.anthropic_adapter import AnthropicModel

        return AnthropicModel(model=name) if name else AnthropicModel()
    if kind == "openai":
        if not name:
            raise SystemExit("--model openai needs --model-name")
        from freight_agents.llm.openai_adapter import OpenAIModel

        return OpenAIModel(model=name)
    raise SystemExit(f"unknown model kind {kind}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="freight-claims")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state directory")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="process every email in an inbox folder")
    run.add_argument("--inbox", type=Path, required=True)
    run.add_argument("--tms", type=Path, required=True)
    run.add_argument("--model", choices=["replay", "anthropic", "openai"], default="replay")
    run.add_argument("--model-name")
    run.add_argument("--cassette", type=Path)

    commands.add_parser("pending", help="list sends waiting for approval")

    approve = commands.add_parser("approve", help="approve one pending send")
    approve.add_argument("approval_id")
    approve.add_argument("--by", required=True)
    approve.add_argument("--tms", type=Path, required=True)

    show = commands.add_parser("show", help="print a case and its history")
    show.add_argument("case_id")

    # Accept --state after the subcommand too, as people type it.
    for sub in (run, approve, show, commands.choices["pending"]):
        sub.add_argument("--state", type=Path, default=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    stores = Stores.at(args.state)

    if args.command == "show":
        case = stores.engine.view(args.case_id)
        print(f"{case.case_id}  state: {case.state}")
        for event in case.history:
            detail = event.payload.get("event") or ", ".join(sorted(event.payload.get("data", {})))
            when = event.at.isoformat()
            print(f"  {event.seq:>3}  {when}  {event.type:<16} {detail}  ({event.actor})")
        return 0

    if args.command == "pending":
        for item in stores.approvals.pending():
            print(f"{item.id}  case {item.case_id}  {item.tool}  to {item.args.get('to')}")
            print(f"    subject: {item.args.get('subject')}")
            print(f"    {item.args.get('body')}")
        return 0

    if args.command == "approve":
        intake = ClaimsIntake(model=None, tms=FixtureTms(args.tms), stores=stores)
        case = intake.approve(args.approval_id, approver=args.by)
        print(f"sent; {case.case_id} is now {case.state}")
        return 0

    model = _model(args.model, args.model_name, args.cassette)
    intake = ClaimsIntake(model=model, tms=FixtureTms(args.tms), stores=stores)
    for message in DirectoryInbox(args.inbox).messages():
        case = intake.process(message)
        print(f"{case.case_id}  {case.state:<14} {message.subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
