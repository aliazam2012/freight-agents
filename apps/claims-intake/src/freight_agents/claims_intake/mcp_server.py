"""claims-intake over MCP, for Claude Code, Codex or any MCP client.

Reads are open. The one write a client may ask for, a request for missing
claim details, runs the same internal tool an agent would, through the same
hooks, and stops in the approval queue. No MCP tool approves or sends.
"""

from __future__ import annotations

import uuid
from typing import Any

from freight_agents.agentcore.guards import cap_size, redact_pii
from freight_agents.agentcore.hooks import HookContext
from freight_agents.agentcore.tools import Risk, Tool, ToolRegistry, strict_schema, tool
from freight_agents.knowledge.index import SearchIn, search_tool
from freight_agents.llm import ToolSpec
from freight_agents.mcp.bridge import Route, RouteError, build_server
from pydantic import BaseModel, ValidationError

from .domain import ClaimFields, missing_requirements
from .tools import CaseDeps, DraftIn, LookupIn, build_tools
from .workflow import CLAIMS_ADDRESS, ClaimsIntake

INSTRUCTIONS = (
    "Freight claims intake. Read cases, shipments and the claim rules. "
    "request_missing_info drafts an email to the claimant; a person approves it before it is sent."
)


class GetCaseIn(BaseModel):
    case_id: str


class GetCaseOut(BaseModel):
    case_id: str
    state: str
    fields: dict[str, Any] | None
    missing: list[str]
    filing_window: str | None
    history: list[str]


class ListPendingIn(BaseModel):
    pass


class PendingSend(BaseModel):
    approval_id: str
    case_id: str | None
    to: str
    subject: str


class ListPendingOut(BaseModel):
    sends: list[PendingSend]


class RequestInfoIn(DraftIn):
    case_id: str


def _specs() -> list[ToolSpec]:
    described: list[tuple[str, str, type[BaseModel]]] = [
        ("get_case", "A claim case: state, fields, what is missing, recent history.", GetCaseIn),
        ("list_pending_sends", "Emails waiting for a person to approve.", ListPendingIn),
        ("lookup_shipment", "Find a shipment by PRO or bill of lading number.", LookupIn),
        (
            "search_knowledge",
            "Search the sourced freight claim rules; returns citations.",
            SearchIn,
        ),
        (
            "request_missing_info",
            "Draft an email asking the claimant for missing details. A person approves it first.",
            RequestInfoIn,
        ),
    ]
    return [ToolSpec(name=n, description=d, input_schema=strict_schema(m)) for n, d, m in described]


def build_claims_server(intake: ClaimsIntake) -> Any:
    engine = intake.stores.engine

    @tool(name="get_case", description="Read a claim case.", risk=Risk.READ)
    def get_case(args: GetCaseIn) -> GetCaseOut:
        case = engine.view(args.case_id)
        raw = case.data.get("fields")
        missing = missing_requirements(ClaimFields.model_validate(raw)) if raw else ["fields"]
        history = [str(e.payload.get("event") or e.type) for e in case.history[-10:]]
        return GetCaseOut(
            case_id=case.case_id,
            state=case.state,
            fields=raw,
            missing=missing,
            filing_window=case.data.get("filing_window"),
            history=history,
        )

    @tool(name="list_pending_sends", description="List sends awaiting approval.", risk=Risk.READ)
    def list_pending_sends(args: ListPendingIn) -> ListPendingOut:
        return ListPendingOut(
            sends=[
                PendingSend(
                    approval_id=a.id,
                    case_id=a.case_id,
                    to=str(a.args.get("to", "")),
                    subject=str(a.args.get("subject", "")),
                )
                for a in intake.stores.approvals.pending()
            ]
        )

    deps = CaseDeps(
        "", engine, intake.tms, intake.stores.transport, CLAIMS_ADDRESS, intake.clock().date()
    )
    lookup = build_tools(deps)["lookup_shipment"]
    reads: dict[str, Tool] = {
        "get_case": get_case,
        "list_pending_sends": list_pending_sends,
        "lookup_shipment": lookup,
        "search_knowledge": search_tool(intake.index),
    }

    def route(name: str, args: dict[str, Any]) -> Route:
        run_id = f"mcp-{uuid.uuid4().hex[:10]}"
        if name in reads:
            if name == "get_case" and "case_id" in args and not engine.exists(str(args["case_id"])):
                raise RouteError("not_found", f"no case {args['case_id']}")
            ctx = HookContext(run_id=run_id, agent="mcp", now=intake.clock())
            return Route(ToolRegistry([reads[name]]), [], [redact_pii, cap_size()], ctx, name, args)
        try:
            request = RequestInfoIn.model_validate(args)
        except ValidationError as exc:
            raise RouteError("invalid_input", str(exc.errors(include_url=False))) from None
        if not engine.exists(request.case_id):
            raise RouteError("not_found", f"no case {request.case_id}")
        case = engine.view(request.case_id)
        record = case.data["email"]
        registry, pre, post = intake.toolkit(case.case_id, record, ["draft_info_request"])
        ctx = intake.context(run_id, "mcp", case, record)
        draft = request.model_dump(exclude={"case_id"})
        return Route(registry, pre, post, ctx, "draft_info_request", draft)

    return build_server("freight-claims", _specs(), route, intake.stores.audit, INSTRUCTIONS)
