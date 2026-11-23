r"""The claims-intake state machine.

received -> triaged -> extracted -> ready_to_file -> handed_off
                                 \-> needs_info -> awaiting_reply -> triaged (reply)
                                                                 \-> needs_info (overdue)
received -> not_a_claim -> closed
"""

from __future__ import annotations

from typing import Any

from freight_agents.statecore.machine import CaseView, StateMachine, Transition

from .domain import ClaimFields, missing_requirements

REPLY_OVERDUE_DAYS = 7


def _missing(case: CaseView) -> list[str]:
    raw = case.data.get("fields")
    if not raw:
        return ["fields"]
    return missing_requirements(ClaimFields.model_validate(raw))


def _nothing_missing(case: CaseView, payload: dict[str, Any]) -> str | None:
    missing = _missing(case)
    return f"still missing: {', '.join(missing)}" if missing else None


def _something_missing(case: CaseView, payload: dict[str, Any]) -> str | None:
    return None if _missing(case) else "nothing is missing; use complete"


CLAIMS_MACHINE = StateMachine(
    name="claims_intake",
    initial="received",
    transitions=[
        Transition("received", "triage_claim", "triaged"),
        Transition("received", "triage_other", "not_a_claim"),
        Transition("not_a_claim", "close", "closed"),
        Transition("triaged", "extracted", "extracted"),
        Transition("extracted", "complete", "ready_to_file", guard=_nothing_missing),
        Transition("extracted", "incomplete", "needs_info", guard=_something_missing),
        Transition("needs_info", "request_sent", "awaiting_reply"),
        Transition("awaiting_reply", "reply_received", "triaged"),
        Transition("awaiting_reply", "reply_overdue", "needs_info"),
        Transition("ready_to_file", "handoff", "handed_off"),
    ],
    terminal={"handed_off", "closed"},
)
