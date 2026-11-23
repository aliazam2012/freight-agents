"""The claims-intake tools. Each is a plain function over one case's dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from freight_agents.agentcore.tools import Risk, Tool, tool
from freight_agents.integrations.tms import Shipment, TmsClient
from freight_agents.integrations.transport import Transport
from freight_agents.statecore.engine import CaseEngine
from pydantic import BaseModel

from .domain import ClaimFields, filing_window, missing_requirements


@dataclass(frozen=True)
class CaseDeps:
    case_id: str
    engine: CaseEngine
    tms: TmsClient
    transport: Transport
    claims_address: str
    received_on: date


class TriageIn(BaseModel):
    label: Literal["claim", "status_question", "other"]
    reason: str


class TriageOut(BaseModel):
    recorded: bool


class LookupIn(BaseModel):
    pro_number: str | None
    bol_number: str | None


class LookupOut(BaseModel):
    found: bool
    shipment: Shipment | None


class SaveIn(BaseModel):
    fields: ClaimFields


class SaveOut(BaseModel):
    saved: bool
    missing: list[str]
    filing_window: str


class DraftIn(BaseModel):
    to: str
    missing: list[str]
    subject: str
    body: str


class DraftOut(BaseModel):
    message_id: str


def build_tools(deps: CaseDeps) -> dict[str, Tool]:
    @tool(name="submit_triage", description="Record how this email is classified.", risk=Risk.READ)
    def submit_triage(args: TriageIn) -> TriageOut:
        return TriageOut(recorded=True)

    @tool(
        name="lookup_shipment",
        description="Find the shipment in the TMS by PRO number or bill of lading number.",
        risk=Risk.READ,
    )
    def lookup_shipment(args: LookupIn) -> LookupOut:
        found = None
        if args.pro_number:
            found = deps.tms.get_shipment(args.pro_number)
        if found is None and args.bol_number:
            found = deps.tms.find_by_bol(args.bol_number)
        return LookupOut(found=found is not None, shipment=found)

    @tool(
        name="save_claim_fields",
        description="Save the claim fields for this case. Unknown fields are null.",
        risk=Risk.WRITE,
    )
    def save_claim_fields(args: SaveIn) -> SaveOut:
        window = filing_window(args.fields.delivery_date, deps.received_on)
        deps.engine.patch(
            deps.case_id,
            {"fields": args.fields.model_dump(mode="json"), "filing_window": window},
            actor="agent:extraction",
        )
        return SaveOut(saved=True, missing=missing_requirements(args.fields), filing_window=window)

    @tool(
        name="draft_info_request",
        description=(
            "Email the claimant to ask for missing claim details. A person approves it first."
        ),
        risk=Risk.SEND,
    )
    def draft_info_request(args: DraftIn) -> DraftOut:
        message_id = deps.transport.send(
            sender=deps.claims_address, to=args.to, subject=args.subject, body=args.body
        )
        return DraftOut(message_id=message_id)

    tools = (submit_triage, lookup_shipment, save_claim_fields, draft_info_request)
    return {t.name: t for t in tools}
