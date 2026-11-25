"""carrier-filing over MCP: read claims, deadlines and pending sends; ask a carrier's status.

No MCP tool files a claim, approves or sends. check_status runs the same read tool the
desk uses, through the same hooks.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from freight_agents.agentcore.guards import cap_size
from freight_agents.agentcore.hooks import HookContext
from freight_agents.agentcore.tools import Risk, Tool, ToolRegistry, strict_schema, tool
from freight_agents.carrier_filing.deadlines import deadlines
from freight_agents.carrier_filing.desk import FilingDesk
from freight_agents.knowledge.index import Bm25Index, SearchIn, default_corpus, search_tool
from freight_agents.llm import ToolSpec
from freight_agents.mcp.bridge import Route, RouteError, build_server
from pydantic import BaseModel

INSTRUCTIONS = (
    "Freight claims filed with carriers. Read a claim, its 49 CFR 370 deadlines and the sends "
    "waiting for approval; ask the carrier's status; search the claim rules. Filing, approving "
    "and sending are not available over MCP."
)


class CaseIn(BaseModel):
    case_id: str


class ClaimOut(BaseModel):
    case_id: str
    state: str
    carrier: str
    receipt: dict[str, Any] | None
    disposition: str | None
    history: list[str]


class DeadlinesOut(BaseModel):
    case_id: str
    received_on: dt.date | None
    acknowledgement_due: dt.date | None
    disposition_due: dt.date | None


class PendingIn(BaseModel):
    pass


class PendingSend(BaseModel):
    approval_id: str
    case_id: str | None
    tool: str
    to: str
    subject: str


class PendingOut(BaseModel):
    sends: list[PendingSend]


def _specs() -> list[ToolSpec]:
    described: list[tuple[str, str, type[BaseModel]]] = [
        ("get_claim", "A filed claim: state, carrier, receipt, disposition, history.", CaseIn),
        ("claim_deadlines", "The carrier's 370.5 and 370.9 dates for a claim.", CaseIn),
        ("list_pending_sends", "Claim emails and follow-ups waiting for a person.", PendingIn),
        ("check_status", "Ask the carrier for the claim's status and update the claim.", CaseIn),
        (
            "search_claim_rules",
            "Search the sourced freight claim rules; returns citations.",
            SearchIn,
        ),
    ]
    return [ToolSpec(name=n, description=d, input_schema=strict_schema(m)) for n, d, m in described]


def build_filing_server(desk: FilingDesk) -> Any:
    engine = desk.stores.engine

    def claim(case_id: str) -> ClaimOut:
        case = engine.view(case_id)
        return ClaimOut(
            case_id=case.case_id,
            state=case.state,
            carrier=case.data["packet"]["carrier"]["name"],
            receipt=case.data.get("receipt"),
            disposition=case.data.get("disposition"),
            history=[str(e.payload.get("event") or e.type) for e in case.history[-10:]],
        )

    @tool(name="get_claim", description="Read a claim.", risk=Risk.READ)
    def get_claim(args: CaseIn) -> ClaimOut:
        return claim(args.case_id)

    @tool(name="claim_deadlines", description="A claim's 370 deadlines.", risk=Risk.READ)
    def claim_deadlines(args: CaseIn) -> DeadlinesOut:
        receipt = engine.view(args.case_id).data.get("receipt")
        if not receipt:
            return DeadlinesOut(
                case_id=args.case_id,
                received_on=None,
                acknowledgement_due=None,
                disposition_due=None,
            )
        d = deadlines(dt.date.fromisoformat(receipt["received_on"]))
        return DeadlinesOut(
            case_id=args.case_id,
            received_on=d.received_on,
            acknowledgement_due=d.acknowledgement_due,
            disposition_due=d.disposition_due,
        )

    @tool(name="list_pending_sends", description="Sends awaiting approval.", risk=Risk.READ)
    def list_pending_sends(args: PendingIn) -> PendingOut:
        return PendingOut(
            sends=[
                PendingSend(
                    approval_id=a.id,
                    case_id=a.case_id,
                    tool=a.tool,
                    to=str(a.args.get("to", "")),
                    subject=str(a.args.get("subject", "")),
                )
                for a in desk.stores.approvals.pending()
            ]
        )

    @tool(name="check_status", description="Ask the carrier and update the claim.", risk=Risk.READ)
    def check_status(args: CaseIn) -> ClaimOut:
        desk.check(args.case_id)
        return claim(args.case_id)

    rules = search_tool(Bm25Index(default_corpus()))
    reads: dict[str, Tool] = {
        "get_claim": get_claim,
        "claim_deadlines": claim_deadlines,
        "list_pending_sends": list_pending_sends,
        "check_status": check_status,
        "search_claim_rules": rules,
    }

    def route(name: str, args: dict[str, Any]) -> Route:
        if name not in reads:
            raise RouteError("unknown_tool", f"no tool {name}")
        if "case_id" in args and not engine.exists(str(args["case_id"])):
            raise RouteError("not_found", f"no claim {args['case_id']}")
        ctx = HookContext(run_id=f"mcp-{uuid.uuid4().hex[:10]}", agent="mcp", now=desk.clock())
        call_name = rules.name if name == "search_claim_rules" else name
        return Route(ToolRegistry([reads[name]]), [], [cap_size()], ctx, call_name, args)

    return build_server("freight-filing", _specs(), route, desk.stores.audit, INSTRUCTIONS)
