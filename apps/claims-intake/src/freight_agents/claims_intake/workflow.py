"""Claims intake: one email becomes one claim case.

triage agent -> extraction agent -> deterministic rule check -> drafting agent
(only when details are missing). Agents call tools; tools pass through the
hooks; only the state engine moves the case. Nothing leaves without approval.
"""

from __future__ import annotations

import hashlib
import html
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from freight_agents.agentcore.agent import Agent, AgentResult, Budget
from freight_agents.agentcore.approvals import ApprovalQueue, AuditLog, IdempotencyStore
from freight_agents.agentcore.guards import (
    approval_gate,
    cap_size,
    idempotency,
    redact_pii,
    state_allowlist,
    taint_guard,
)
from freight_agents.agentcore.hooks import ALLOW, Decision, Deny, HookContext, PreHook, run_tool
from freight_agents.agentcore.taint import TaintSet
from freight_agents.agentcore.tools import Tool, ToolRegistry
from freight_agents.integrations.email import EmailMessage
from freight_agents.integrations.tms import TmsClient
from freight_agents.integrations.transport import FileTransport, Transport
from freight_agents.knowledge.index import Bm25Index, default_corpus, search_tool
from freight_agents.llm import Model, TextPart, ToolCall
from freight_agents.statecore.engine import CaseEngine
from freight_agents.statecore.machine import CaseView
from freight_agents.statecore.store import SqliteEventStore
from freight_agents.telemetry.meter import CostMeter

from . import prompts
from .domain import ClaimFields, missing_requirements
from .machine import CLAIMS_MACHINE, REPLY_OVERDUE_DAYS
from .tools import CaseDeps, build_tools

log = logging.getLogger(__name__)

CLAIMS_ADDRESS = "claims@example.org"
TRIAGE_ATTEMPTS = 2

POLICY: dict[str, set[str]] = {
    "submit_triage": {"received"},
    "lookup_shipment": {"triaged"},
    "search_knowledge": {"triaged", "needs_info"},
    "save_claim_fields": {"triaged"},
    "draft_info_request": {"needs_info"},
}

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Stores:
    engine: CaseEngine
    approvals: ApprovalQueue
    idempotency: IdempotencyStore
    audit: AuditLog
    transport: Transport

    @classmethod
    def at(cls, directory: Path, clock: Clock = _utc_now) -> Stores:
        directory.mkdir(parents=True, exist_ok=True)
        return cls(
            engine=CaseEngine(
                CLAIMS_MACHINE, SqliteEventStore(directory / "events.sqlite3"), clock
            ),
            approvals=ApprovalQueue(directory / "approvals.sqlite3"),
            idempotency=IdempotencyStore(directory / "idempotency.sqlite3"),
            audit=AuditLog(directory / "audit.sqlite3"),
            transport=FileTransport(directory / "outbox"),
        )

    def audit_rows(self, tool: str | None = None) -> list[dict[str, Any]]:
        return self.audit.rows(tool)


def case_id_for(message: EmailMessage) -> str:
    return "clm_" + hashlib.sha256(message.message_id.encode("utf-8")).hexdigest()[:16]


def email_record(message: EmailMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "sender": message.sender,
        "to": message.to,
        "subject": message.subject,
        "date": message.date.isoformat() if message.date else None,
        "text": message.text,
        "attachments": [
            {"filename": a.filename, "media_type": a.media_type} for a in message.attachments
        ],
    }


def taint_from(record: dict[str, Any]) -> TaintSet:
    taint = TaintSet()
    taint.add(record["sender"], "email.from")
    taint.add(record["subject"], "email.subject")
    taint.add(record["text"], "email.body")
    for address in record["to"]:
        taint.add(address, "email.to")
    for attachment in record["attachments"]:
        taint.add(attachment["filename"], "email.attachment")
    return taint


def render_email(record: dict[str, Any]) -> str:
    """The email as a document block; escaped so its text cannot close the block."""
    names = ", ".join(f"{a['filename']} ({a['media_type']})" for a in record["attachments"])
    fields = (
        ("from", record["sender"]),
        ("subject", record["subject"]),
        ("date", record["date"] or "unknown"),
        ("attachments", names or "none"),
        ("body", record["text"]),
    )
    inner = "\n".join(f"<{tag}>{html.escape(str(value))}</{tag}>" for tag, value in fields)
    return f"<document>\n{inner}\n</document>"


def recipient_policy(claimant: str) -> PreHook:
    """Outbound mail goes to the claimant on the case and to no one else."""

    def hook(tool: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
        if tool.name == "draft_info_request" and args.get("to", "").lower() != claimant:
            if ctx.taint.tainted(args.get("to", "")):
                return ALLOW  # the taint guard names the real reason
            return Deny("recipient", "mail may go only to the claimant on this case")
        return ALLOW

    return hook


class Assessor(Protocol):
    """Looks at a damage claim's photos; hands the case off itself, or leaves it for a person."""

    def assess(self, case_id: str, fields: ClaimFields, message: EmailMessage) -> object: ...


class ClaimsIntake:
    def __init__(
        self,
        model: Model | None,
        tms: TmsClient,
        stores: Stores,
        clock: Clock = _utc_now,
        index: Bm25Index | None = None,
        budget: Budget | None = None,
        assessor: Assessor | None = None,
    ) -> None:
        self.model = model
        self.assessor = assessor
        self.tms = tms
        self.stores = stores
        self.clock = clock
        self.index = index or Bm25Index(default_corpus())
        self.budget = budget or Budget(max_turns=6, max_tool_calls=8, max_cost_usd=0.50)
        self.meter = CostMeter()

    # The whole flow for one email.
    def process(self, message: EmailMessage) -> CaseView:
        engine = self.stores.engine
        case_id = case_id_for(message)
        if engine.exists(case_id):
            return engine.view(case_id)
        record = email_record(message)
        engine.open(case_id, {"email": record}, actor="inbox")

        label = self._triage(case_id, record)
        if label is None:
            return engine.view(case_id)
        if label != "claim":
            return engine.fire(case_id, "triage_other", {"triage": label}, actor="agent:triage")
        engine.fire(case_id, "triage_claim", actor="agent:triage")

        self._run(
            "extraction",
            prompts.EXTRACTION,
            case_id,
            record,
            ["lookup_shipment", "search_knowledge", "save_claim_fields"],
        )
        case = engine.view(case_id)
        fields = case.data.get("fields") or {k: None for k in ClaimFields.model_fields}
        engine.fire(case_id, "extracted", {"fields": fields}, actor="workflow")
        claim = ClaimFields.model_validate(fields)
        missing = missing_requirements(claim)
        if not missing:
            ready = engine.fire(case_id, "complete", actor="workflow")
            photos = [a for a in message.attachments if a.media_type.startswith("image/")]
            if self.assessor is None or claim.claim_type != "damage" or not photos:
                return ready
            try:
                self.assessor.assess(case_id, claim, message)
            except Exception as exc:  # the claim stays ready: freight-damage run or a person
                log.exception("assessing %s failed", case_id)
                failed = {"assessment_failed": f"{type(exc).__name__}: {exc}"}
                engine.patch(case_id, failed, actor="workflow")
            return engine.view(case_id)
        engine.fire(case_id, "incomplete", {"missing": missing}, actor="workflow")

        note = (
            f"Claimant email: {record['sender']}\nMissing: {', '.join(missing)}\n"
            + render_email(record)
        )
        self._run("drafting", prompts.DRAFTING, case_id, record, ["draft_info_request"], note)
        return engine.view(case_id)

    def hand_off(
        self, case_id: str, amount_usd: float, assessment: dict[str, Any], by: str = "workflow"
    ) -> CaseView:
        """File the assessed amount: carrier-filing picks the case up from here.

        The amount must be above zero and no more than the claimant asked for; the
        claimant's own amount is kept beside it.
        """
        case = self.stores.engine.view(case_id)
        fields = ClaimFields.model_validate(case.data["fields"])
        claimed = fields.claimed_amount_usd or 0.0
        if not 0 < amount_usd <= claimed:
            raise ValueError(f"amount {amount_usd} is outside the claimed {claimed}")
        assessed = fields.model_copy(update={"claimed_amount_usd": amount_usd})
        return self.stores.engine.fire(
            case_id,
            "handoff",
            {
                "fields": assessed.model_dump(mode="json"),
                "claimant_amount_usd": claimed,
                "assessment": assessment,
            },
            actor=by,
        )

    def approve(self, approval_id: str, approver: str) -> CaseView:
        """A person approved one exact send: run it, then move the case on."""
        approval = self.stores.approvals.get(approval_id)
        if approval.case_id is None:
            raise LookupError(f"approval {approval_id} is not tied to a case")
        status = self.stores.approvals.status(approval_id)
        if status == "pending":
            self.stores.approvals.approve(approval_id, approver)
        elif status != "approved":  # an approved send that failed earlier is retried
            raise LookupError(f"approval {approval_id} is {status}, not pending")
        case = self.stores.engine.view(approval.case_id)
        record = case.data["email"]
        registry, pre, post = self.toolkit(approval.case_id, record, [approval.tool])
        ctx = self.context(f"approve-{approval_id}", f"person:{approver}", case, record)
        call = ToolCall(id=f"approved-{approval_id}", name=approval.tool, args=approval.args)
        outcome = run_tool(call, registry, pre, post, ctx, self.stores.audit)
        if outcome.status != "ok":
            self.stores.approvals.release(approval_id)
            raise RuntimeError(f"approved send did not run: {outcome.code} {outcome.reason}")
        sent = (outcome.output or {}).get("message_id")
        self.stores.engine.fire(
            approval.case_id, "request_sent", {"sent_message_id": sent}, actor=f"person:{approver}"
        )
        self.stores.engine.schedule(
            approval.case_id, "reply_overdue", self.clock() + timedelta(days=REPLY_OVERDUE_DAYS)
        )
        return self.stores.engine.view(approval.case_id)

    def _triage(self, case_id: str, record: dict[str, Any]) -> str | None:
        for attempt in range(1, TRIAGE_ATTEMPTS + 1):
            result = self._run("triage", prompts.TRIAGE, case_id, record, ["submit_triage"])
            for outcome, call in zip(result.outcomes, _calls(result), strict=False):
                if outcome.tool == "submit_triage" and outcome.status == "ok":
                    return str(call.args["label"])
            if attempt == TRIAGE_ATTEMPTS:
                self.stores.engine.patch(
                    case_id, {"triage": {"status": "failed", "attempts": attempt}}, actor="workflow"
                )
        return None

    def _run(
        self,
        name: str,
        system: str,
        case_id: str,
        record: dict[str, Any],
        tool_names: list[str],
        user_text: str | None = None,
    ) -> AgentResult:
        if self.model is None:
            raise RuntimeError("no model configured; this command needs one")
        registry, pre, post = self.toolkit(case_id, record, tool_names)
        agent = Agent(name, self.model, registry, system, pre, post, self.stores.audit, self.budget)
        case = self.stores.engine.view(case_id)
        ctx = self.context(uuid.uuid4().hex[:12], f"agent:{name}", case, record)
        result = agent.run([TextPart(text=user_text or render_email(record))], ctx)
        self.meter.add(self.model.name, result.usage)
        return result

    def toolkit(
        self, case_id: str, record: dict[str, Any], tool_names: list[str]
    ) -> tuple[ToolRegistry, list[Any], list[Any]]:
        received = datetime.fromisoformat(record["date"]) if record["date"] else self.clock()
        deps = CaseDeps(
            case_id=case_id,
            engine=self.stores.engine,
            tms=self.tms,
            transport=self.stores.transport,
            claims_address=CLAIMS_ADDRESS,
            received_on=received.date(),
        )
        tools = {**build_tools(deps), "search_knowledge": search_tool(self.index)}
        claimant = record["sender"].lower()
        idem_pre, idem_post = idempotency(self.stores.idempotency)
        pre = [
            state_allowlist(POLICY),
            taint_guard({"draft_info_request": {"to": lambda v: str(v).lower() == claimant}}),
            recipient_policy(claimant),
            idem_pre,
            approval_gate(self.stores.approvals),
        ]
        post = [idem_post, redact_pii, cap_size()]
        return ToolRegistry([tools[n] for n in tool_names]), pre, post

    def context(
        self, run_id: str, agent: str, case: CaseView, record: dict[str, Any]
    ) -> HookContext:
        return HookContext(
            run_id=run_id,
            agent=agent,
            now=self.clock(),
            case_id=case.case_id,
            state=case.state,
            taint=taint_from(record),
        )


def _calls(result: AgentResult) -> list[ToolCall]:
    return [
        part
        for message in result.messages
        if message.role == "assistant"
        for part in message.parts
        if isinstance(part, ToolCall)
    ]
