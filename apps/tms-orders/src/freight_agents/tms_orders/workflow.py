"""The whole flow for one tender file, from arrival to a confirmed or declined order.

EDI is parsed by code. PDF and email text go to the model, which may only call
`record_order`. Validation, the TMS write and the reply are code, run through the
hook pipeline: the state allowlist, the taint guard, a check that the order sent
is exactly the order validated, the recipient policy, idempotency and the approval
gate. Every reply waits for a person. A rerun of the same file resumes the case
where it stopped, so a crash or a TMS outage never repeats a step.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from freight_agents.agentcore.approvals import ApprovalQueue, AuditLog, IdempotencyStore
from freight_agents.agentcore.guards import (
    approval_gate,
    cap_size,
    idempotency,
    state_allowlist,
    taint_guard,
)
from freight_agents.agentcore.hooks import ALLOW, Decision, Deny, HookContext, run_tool
from freight_agents.agentcore.taint import TaintSet
from freight_agents.agentcore.tools import Risk, Tool, ToolRegistry, tool
from freight_agents.integrations.documents import DocumentError, pdf_text
from freight_agents.integrations.email import parse_eml
from freight_agents.integrations.http import Unavailable
from freight_agents.integrations.transport import FileTransport, Transport
from freight_agents.integrations.x12 import X12Error, parse_interchange
from freight_agents.llm import Model, ModelTurn, ScriptedModel, ToolCall, Usage
from freight_agents.statecore.engine import CaseEngine
from freight_agents.statecore.machine import CaseView
from freight_agents.statecore.store import SqliteEventStore
from freight_agents.tms_orders.domain import Order, Purpose, Source, Tender
from freight_agents.tms_orders.edi204 import parse_204, write_990
from freight_agents.tms_orders.extract import extract_tender
from freight_agents.tms_orders.machine import ORDERS_MACHINE, POLICY
from freight_agents.tms_orders.submit import submit
from freight_agents.tms_orders.synth import SHIPPER_ADDRESSES, Location
from freight_agents.tms_orders.tms import HttpTms
from freight_agents.tms_orders.validate import validate_order
from pydantic import BaseModel

ORDERS_ADDRESS = "tenders@exfl.example.com"
Clock = Callable[[], dt.datetime]
ModelFor = Callable[[Path], Model]


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


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
                ORDERS_MACHINE, SqliteEventStore(directory / "events.sqlite3"), clock
            ),
            approvals=ApprovalQueue(directory / "approvals.sqlite3"),
            idempotency=IdempotencyStore(directory / "idempotency.sqlite3"),
            audit=AuditLog(directory / "audit.sqlite3"),
            transport=FileTransport(directory / "outbox"),
        )


def load_locations(path: Path) -> set[Location]:
    rows = json.loads(path.read_text())
    return {(str(name), str(street), str(zip_)) for name, street, zip_ in rows}


def _scripted_turns(draft: dict[str, Any]) -> list[ModelTurn]:
    usage = Usage()
    call = ToolCall(id="c1", name="record_order", args=draft)
    return [
        ModelTurn(text="", tool_calls=[call], stop="tool_use", usage=usage, model="reference"),
        ModelTurn(text="Recorded.", tool_calls=[], stop="end", usage=usage, model="reference"),
    ]


def scripted_draft(draft: dict[str, Any]) -> Model:
    """A model that records `draft` and stops: the reference turns for one tender."""
    return ScriptedModel(_scripted_turns(draft), name="reference")


def reference_models(gold: Path) -> ModelFor:
    """Reference mode: each fixture file's model records its gold order; red-team files play
    the scripted model that falls for the injected instruction (redteam.jsonl beside gold)."""
    from freight_agents.tms_orders.extract import draft_of

    scripts: dict[str, list[ModelTurn]] = {}
    for line in gold.read_text().splitlines():
        row = json.loads(line)
        draft = draft_of(Tender.model_validate(row["tender"]))
        scripts[Path(row["file"]).name] = _scripted_turns(draft)
    redteam = gold.with_name("redteam.jsonl")
    if redteam.exists():
        for line in redteam.read_text().splitlines():
            row = json.loads(line)
            turns = [ModelTurn.model_validate(t) for t in row["reference"]]
            scripts[Path(row["file"]).name] = turns

    def model_for(path: Path) -> Model:
        if path.name in scripts:
            return ScriptedModel(list(scripts[path.name]), name="reference")
        usage = Usage()
        return ScriptedModel(
            [
                ModelTurn(
                    text="I cannot read this tender.",
                    tool_calls=[],
                    stop="end",
                    usage=usage,
                    model="reference",
                )
            ]
        )

    return model_for


@dataclass(frozen=True)
class Document:
    source: Source
    reference: str
    text: str
    reply_to: str | None
    received_at: dt.datetime


def read_document(path: Path, now: dt.datetime) -> Document:
    suffix = path.suffix.lower()
    if suffix == ".edi":
        text = path.read_text()
        try:
            ix = parse_interchange(text)
            return Document(Source.EDI, ix.control, text, f"edi:{ix.sender}", now)
        except X12Error:
            return Document(Source.EDI, path.name, text, None, now)
    if suffix == ".pdf":
        try:
            text = pdf_text(path)
        except DocumentError:
            text = ""
        return Document(Source.PDF, path.name, text, None, now)
    message = parse_eml(path.read_bytes())
    text = f"Subject: {message.subject}\n\n{message.text}"
    return Document(
        Source.EMAIL,
        message.message_id or path.name,
        text,
        message.sender.lower() or None,
        message.date or now,
    )


def case_id_for(source: Source, reference: str) -> str:
    return f"{source.value}-" + re.sub(r"[^A-Za-z0-9._@-]", "", reference)


def _strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return {s for v in value.values() for s in _strings(v)}
    if isinstance(value, list):
        return {s for v in value for s in _strings(v)}
    return set()


class SubmitIn(BaseModel):
    purpose: Purpose
    reference: str
    order: Order


class SubmitOut(BaseModel):
    outcome: Literal["created", "duplicate", "changed", "cancelled", "needs_review"]
    order_id: str | None
    version: int | None
    reason: str


class ReplyIn(BaseModel):
    to: str
    subject: str
    body: str


class ReplyOut(BaseModel):
    message_id: str


class OrdersIntake:
    def __init__(
        self,
        stores: Stores,
        tms: HttpTms,
        models: ModelFor,
        locations: set[Location],
        clock: Clock = _utc_now,
    ) -> None:
        self.stores = stores
        self.tms = tms
        self.models = models
        self.locations = locations
        self.clock = clock

    # Arrival and the loop that moves a case as far as it can go without a person.
    def process(self, path: Path) -> CaseView:
        doc = read_document(path, self.clock())
        case_id = case_id_for(doc.source, doc.reference)
        engine = self.stores.engine
        if not engine.exists(case_id):
            engine.open(
                case_id,
                {
                    "file": str(path),
                    "source": doc.source.value,
                    "reference": doc.reference,
                    "document": doc.text,
                    "reply_to": doc.reply_to,
                    "received_at": doc.received_at.isoformat(),
                },
                actor="inbox",
            )
        return self.resume(case_id)

    def resume(self, case_id: str) -> CaseView:
        steps: dict[str, Callable[[CaseView], bool]] = {
            "received": self._parse,
            "parsed": self._validate,
            "validated": self._submit,
            "submitted": lambda c: self._draft(c, accept=True),
            "declining": lambda c: self._draft(c, accept=False),
        }
        while True:
            case = self.stores.engine.view(case_id)
            step = steps.get(case.state)
            if step is None or not step(case):
                return self.stores.engine.view(case_id)

    def _parse(self, case: CaseView) -> bool:
        engine, data = self.stores.engine, case.data
        received = dt.datetime.fromisoformat(data["received_at"])
        source = Source(data["source"])
        if source == Source.EDI:
            try:
                tenders = parse_204(data["document"])
            except X12Error as exc:
                engine.fire(case.case_id, "unreadable", {"reason": str(exc)}, actor="parser")
                return True
            if len(tenders) != 1:
                engine.fire(
                    case.case_id,
                    "unreadable",
                    {"reason": f"expected one 204, found {len(tenders)}"},
                    actor="parser",
                )
                return True
            tender = tenders[0]
        else:
            result = extract_tender(
                self.models(Path(data["file"])),
                data["document"],
                source,
                data["reference"],
                received,
            )
            if result.tender is None:
                reason = f"missing {', '.join(result.missing)}" if result.missing else "no order"
                engine.fire(case.case_id, "unreadable", {"reason": reason}, actor="agent:extract")
                return True
            tender = result.tender
        update: dict[str, Any] = {"tender": tender.model_dump(mode="json")}
        if data.get("reply_to") is None:
            update["reply_to"] = SHIPPER_ADDRESSES.get(tender.order.shipper.name)
        engine.fire(case.case_id, "parsed", update, actor="parser")
        return True

    def _validate(self, case: CaseView) -> bool:
        tender = Tender.model_validate(case.data["tender"])
        findings = (
            []
            if tender.purpose == Purpose.CANCEL
            else validate_order(tender.order, self.clock(), known=self.locations)
        )
        rows = [f.model_dump() for f in findings]
        severities = {f.severity for f in findings}
        if case.data.get("reply_to") is None:
            rows.append(
                {
                    "rule": "reply.address",
                    "severity": "review",
                    "source": "workflow",
                    "message": "no reply address is known for this shipper",
                }
            )
            severities.add("review")
        event = (
            "blocked" if "block" in severities else "review" if "review" in severities else "valid"
        )
        payload: dict[str, Any] = {"findings": rows}
        if event == "valid":
            payload["validated_order"] = case.data["tender"]["order"]
        self.stores.engine.fire(case.case_id, event, payload, actor="validator")
        return True

    def _submit(self, case: CaseView) -> bool:
        tender = case.data["tender"]
        call = ToolCall(
            id=f"submit-{case.case_id}",
            name="submit_order",
            args={
                "purpose": tender["purpose"],
                "reference": tender["reference"],
                "order": tender["order"],
            },
        )
        outcome = self._run(case, call, "workflow")
        engine = self.stores.engine
        # A raised outage is not cached by the idempotency hook, so a rerun retries it.
        if outcome.status == "error" and (outcome.reason or "").startswith(
            f"{Unavailable.__name__}:"
        ):
            engine.patch(case.case_id, {"waiting": outcome.reason}, actor="workflow")
            return False  # the TMS is down; a later run resumes here
        if outcome.status not in ("ok", "replayed"):
            engine.fire(
                case.case_id,
                "held",
                {"reason": f"{outcome.code}: {outcome.reason}"},
                actor="workflow",
            )
            return True
        out = SubmitOut.model_validate(outcome.output)
        receipt = {"order_id": out.order_id, "version": out.version, "outcome": out.outcome}
        if out.outcome == "duplicate":
            engine.fire(case.case_id, "duplicate", {"receipt": receipt}, actor="workflow")
        elif out.outcome == "needs_review":
            engine.fire(case.case_id, "held", {"reason": out.reason}, actor="workflow")
        else:
            engine.fire(case.case_id, "submitted", {"receipt": receipt}, actor="workflow")
        return True

    def _draft(self, case: CaseView, accept: bool) -> bool:
        reply = self._reply(case, accept)
        call = ToolCall(id=f"reply-{case.case_id}-{accept}", name="send_reply", args=reply)
        outcome = self._run(case, call, "workflow")
        if outcome.status != "pending":
            raise RuntimeError(f"a reply ran without approval: {outcome.status} {outcome.reason}")
        approval = (outcome.output or {}).get("approval_id")
        event = "drafted" if accept else "drafted_decline"
        self.stores.engine.fire(case.case_id, event, {"approval_id": approval}, actor="workflow")
        return True

    def _reply(self, case: CaseView, accept: bool) -> dict[str, str]:
        data = case.data
        to = data.get("reply_to") or ""
        tender = Tender.model_validate(data["tender"]) if data.get("tender") else None
        load = tender.order.tender_id if tender else data["reference"]
        reasons = [f["message"] for f in data.get("findings", []) if f["severity"] != "notice"]
        if data.get("reason"):
            reasons.append(data["reason"])
        if tender is not None and tender.source == Source.EDI:
            when = f"{self.clock():%Y%m%d%H%M}"
            control = str(int(hashlib.sha256(case.case_id.encode()).hexdigest(), 16) % 10**9)
            body = write_990(tender, accept=accept, control=control, when=when)
            return {"to": to, "subject": f"990 for load {load}", "body": body}
        if accept and tender is not None:
            receipt = data.get("receipt", {})
            what = {
                "original": "load",
                "change": "change to load",
                "cancel": "cancellation of load",
            }[tender.purpose.value]
            notices = [f["message"] for f in data.get("findings", []) if f["severity"] == "notice"]
            lines = [
                f"We accept the {what} {load}.",
                f"Our order {receipt.get('order_id')}, version {receipt.get('version')}.",
                *notices,
                "",
                "Example Freight Lines tender desk",
            ]
            return {"to": to, "subject": f"Accepted: {what} {load}", "body": "\n".join(lines)}
        lines = [
            f"We cannot accept load {load}.",
            *[f"- {r}" for r in reasons],
            "",
            "Example Freight Lines tender desk",
        ]
        return {"to": to, "subject": f"Declined: load {load}", "body": "\n".join(lines)}

    # A person's actions.
    def approve(self, approval_id: str, approver: str) -> CaseView:
        approval = self.stores.approvals.get(approval_id)
        if approval.case_id is None:
            raise LookupError(f"approval {approval_id} is not tied to a case")
        status = self.stores.approvals.status(approval_id)
        if status == "pending":
            self.stores.approvals.approve(approval_id, approver)
        elif status != "approved":
            raise LookupError(f"approval {approval_id} is {status}, not pending")
        case = self.stores.engine.view(approval.case_id)
        call = ToolCall(id=f"approved-{approval_id}", name=approval.tool, args=approval.args)
        outcome = self._run(case, call, f"person:{approver}")
        if outcome.status != "ok":
            self.stores.approvals.release(approval_id)
            raise RuntimeError(f"approved reply did not run: {outcome.code} {outcome.reason}")
        event = "sent" if case.state == "confirmation_pending" else "sent_decline"
        self.stores.engine.fire(
            case.case_id,
            event,
            {"sent": (outcome.output or {}).get("message_id")},
            actor=f"person:{approver}",
        )
        return self.stores.engine.view(case.case_id)

    def review(self, case_id: str, decision: Literal["submit", "decline"], by: str) -> CaseView:
        case = self.stores.engine.view(case_id)
        if decision == "submit":
            self.stores.engine.fire(
                case_id,
                "person_submit",
                {
                    "validated_order": case.data["tender"]["order"]
                    if case.data.get("tender")
                    else None
                },
                actor=f"person:{by}",
            )
        else:
            self.stores.engine.fire(case_id, "person_decline", actor=f"person:{by}")
        return self.resume(case_id)

    # Tools and hooks.
    def toolkit(self, case: CaseView) -> tuple[ToolRegistry, list[Any], list[Any]]:
        data = case.data
        reply_to = (data.get("reply_to") or "").lower()
        validated = data.get("validated_order")
        allowed = _strings(validated)

        def matches_validated(t: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
            if t.name != "submit_order":
                return ALLOW
            if validated is None or args.get("order") != validated:
                return Deny("not_validated", "the order differs from the one validation passed")
            return ALLOW

        def recipient_policy(t: Tool, args: dict[str, Any], ctx: HookContext) -> Decision:
            if t.name == "send_reply" and str(args.get("to", "")).lower() != reply_to:
                return Deny("recipient", "a reply goes only to the tender's sender")
            return ALLOW

        idem_pre, idem_post = idempotency(self.stores.idempotency)
        pre = [
            state_allowlist(POLICY),
            taint_guard(
                {
                    "submit_order": {"order": lambda v: v in allowed},
                    "send_reply": {"to": lambda v: str(v).lower() == reply_to},
                }
            ),
            matches_validated,
            recipient_policy,
            idem_pre,
            approval_gate(self.stores.approvals),
        ]
        return ToolRegistry(self._tools(case)), pre, [idem_post, cap_size()]

    def _tools(self, case: CaseView) -> list[Tool]:
        data = case.data
        received = dt.datetime.fromisoformat(data["received_at"])
        source = Source(data["source"])

        @tool(
            name="submit_order",
            description="Create, change or cancel the TMS order for a "
            "validated tender, exactly once.",
            risk=Risk.WRITE,
        )
        def submit_order(args: SubmitIn) -> SubmitOut:
            tender = Tender(
                source=source,
                purpose=args.purpose,
                order=args.order,
                reference=args.reference,
                received_at=received,
            )
            result = submit(self.tms, tender)
            r = result.receipt
            return SubmitOut(
                outcome=result.outcome,
                order_id=r.order_id if r else None,
                version=r.version if r else None,
                reason=result.reason,
            )

        @tool(
            name="send_reply",
            description="Send the tender's sender a confirmation or a "
            "decline. A person approves every send.",
            risk=Risk.SEND,
        )
        def send_reply(args: ReplyIn) -> ReplyOut:
            sent = self.stores.transport.send(
                sender=ORDERS_ADDRESS, to=args.to, subject=args.subject, body=args.body
            )
            return ReplyOut(message_id=sent)

        return [submit_order, send_reply]

    def context(self, case: CaseView, actor: str) -> HookContext:
        taint = TaintSet()
        taint.add(case.data.get("document", ""), f"{case.data['source']}.document")
        return HookContext(
            run_id=f"{actor}-{case.case_id}",
            agent=actor,
            now=self.clock(),
            case_id=case.case_id,
            state=case.state,
            taint=taint,
        )

    def _run(self, case: CaseView, call: ToolCall, actor: str) -> Any:
        registry, pre, post = self.toolkit(case)
        return run_tool(call, registry, pre, post, self.context(case, actor), self.stores.audit)
