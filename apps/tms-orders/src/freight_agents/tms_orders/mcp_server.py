"""tms-orders over MCP, for Claude Code, Codex or any MCP client.

Reads only: a case, the replies waiting for a person, and a search over the sourced
order rules (EDI guides, hazmat regulations, weight limits). No MCP tool submits an
order, approves or sends; those stay with the workflow and a person.
"""

from __future__ import annotations

import uuid
from typing import Any

from freight_agents.agentcore.guards import cap_size
from freight_agents.agentcore.hooks import HookContext
from freight_agents.agentcore.tools import Risk, Tool, ToolRegistry, strict_schema, tool
from freight_agents.knowledge.index import Bm25Index, Passage, SearchIn, package_corpus, search_tool
from freight_agents.llm import ToolSpec
from freight_agents.mcp.bridge import Route, RouteError, build_server
from freight_agents.tms_orders.workflow import OrdersIntake
from pydantic import BaseModel

INSTRUCTIONS = (
    "Freight load tenders to TMS orders. Read a case, the replies waiting for approval, and "
    "the sourced order rules. Orders, approvals and replies are not available over MCP."
)


class GetCaseIn(BaseModel):
    case_id: str


class GetCaseOut(BaseModel):
    case_id: str
    state: str
    source: str
    tender_id: str | None
    purpose: str | None
    findings: list[dict[str, Any]]
    receipt: dict[str, Any] | None
    history: list[str]


class ListPendingIn(BaseModel):
    pass


class PendingReply(BaseModel):
    approval_id: str
    case_id: str | None
    to: str
    subject: str


class ListPendingOut(BaseModel):
    replies: list[PendingReply]


def order_rules() -> list[Passage]:
    """The order rules this package ships in docs/, with their sources."""
    return package_corpus("freight_agents.tms_orders")


def _specs() -> list[ToolSpec]:
    described: list[tuple[str, str, type[BaseModel]]] = [
        ("get_case", "A tender case: state, tender, findings, TMS receipt, history.", GetCaseIn),
        (
            "list_pending_replies",
            "Confirmations and declines waiting for a person.",
            ListPendingIn,
        ),
        ("search_order_rules", "Search the sourced order rules; returns citations.", SearchIn),
    ]
    return [ToolSpec(name=n, description=d, input_schema=strict_schema(m)) for n, d, m in described]


def build_orders_server(intake: OrdersIntake) -> Any:
    engine = intake.stores.engine

    @tool(name="get_case", description="Read a tender case.", risk=Risk.READ)
    def get_case(args: GetCaseIn) -> GetCaseOut:
        case = engine.view(args.case_id)
        tender = case.data.get("tender") or {}
        return GetCaseOut(
            case_id=case.case_id,
            state=case.state,
            source=case.data["source"],
            tender_id=(tender.get("order") or {}).get("tender_id"),
            purpose=tender.get("purpose"),
            findings=case.data.get("findings", []),
            receipt=case.data.get("receipt"),
            history=[str(e.payload.get("event") or e.type) for e in case.history[-10:]],
        )

    @tool(name="list_pending_replies", description="Replies awaiting approval.", risk=Risk.READ)
    def list_pending_replies(args: ListPendingIn) -> ListPendingOut:
        return ListPendingOut(
            replies=[
                PendingReply(
                    approval_id=a.id,
                    case_id=a.case_id,
                    to=str(a.args.get("to", "")),
                    subject=str(a.args.get("subject", "")),
                )
                for a in intake.stores.approvals.pending()
            ]
        )

    rules = search_tool(Bm25Index(order_rules()))
    reads: dict[str, Tool] = {
        "get_case": get_case,
        "list_pending_replies": list_pending_replies,
        "search_order_rules": rules,
    }

    def route(name: str, args: dict[str, Any]) -> Route:
        if name not in reads:
            raise RouteError("unknown_tool", f"no tool {name}")
        if name == "get_case" and not engine.exists(str(args.get("case_id", ""))):
            raise RouteError("not_found", f"no case {args.get('case_id')}")
        ctx = HookContext(run_id=f"mcp-{uuid.uuid4().hex[:10]}", agent="mcp", now=intake.clock())
        call_name = rules.name if name == "search_order_rules" else name
        registry = ToolRegistry([reads[name]])
        return Route(registry, [], [cap_size()], ctx, call_name, args)

    return build_server("freight-orders", _specs(), route, intake.stores.audit, INSTRUCTIONS)
