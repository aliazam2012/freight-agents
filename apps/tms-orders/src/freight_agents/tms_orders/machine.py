r"""The tms-orders state machine. Only the workflow fires events; the model never moves a case.

received --parsed--> parsed --valid--> validated --submitted--> submitted
    |                  |  \--review--> needs_review <--held--/   |  \--duplicate--> duplicate
    unreadable         blocked                                  drafted
    v                  v                                        v
needs_review       declining --drafted_decline--> decline_pending   confirmation_pending
    |  person_submit --> validated                  |                    |
    |  person_decline --> declining                 sent_decline         sent
                                                    v                    v
                                                 declined            confirmed
"""

from __future__ import annotations

from typing import Any

from freight_agents.statecore.machine import CaseView, StateMachine, Transition


def _has_tender(case: CaseView, payload: dict[str, Any]) -> str | None:
    return None if case.data.get("tender") else "there is no readable tender to submit"


ORDERS_MACHINE = StateMachine(
    name="tms_orders",
    initial="received",
    transitions=[
        Transition("received", "parsed", "parsed"),
        Transition("received", "unreadable", "needs_review"),
        Transition("parsed", "valid", "validated"),
        Transition("parsed", "review", "needs_review"),
        Transition("parsed", "blocked", "declining"),
        Transition("validated", "submitted", "submitted"),
        Transition("validated", "duplicate", "duplicate"),
        Transition("validated", "held", "needs_review"),
        Transition("submitted", "drafted", "confirmation_pending"),
        Transition("confirmation_pending", "sent", "confirmed"),
        Transition("declining", "drafted_decline", "decline_pending"),
        Transition("decline_pending", "sent_decline", "declined"),
        Transition("needs_review", "person_submit", "validated", guard=_has_tender),
        Transition("needs_review", "person_decline", "declining"),
    ],
    terminal={"confirmed", "declined", "duplicate"},
)

# Which tool may run in which state (the state_allowlist guard).
POLICY: dict[str, set[str]] = {
    "submit_order": {"validated"},
    "send_reply": {"submitted", "declining", "confirmation_pending", "decline_pending"},
}
