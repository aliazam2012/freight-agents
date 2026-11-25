r"""The carrier-filing state machine. Only the workflow and the timers fire events.

    ready --filed--> filed --acknowledged--> acknowledged
      |                |  \                    |  \
      filing_failed    |   ack_overdue,        |   disposition_overdue, status_overdue
      v                |   disposition_overdue v
    failed --retry--> ready             followup_pending --followup_sent--> filed or acknowledged
                       resolved <-- (from filed, acknowledged or followup_pending)
"""

from __future__ import annotations

from freight_agents.statecore.machine import StateMachine, Transition

FILING_MACHINE = StateMachine(
    name="carrier_filing",
    initial="ready",
    transitions=[
        Transition("ready", "filed", "filed"),
        Transition("ready", "filing_failed", "failed"),
        Transition("failed", "retry", "ready"),
        Transition("filed", "acknowledged", "acknowledged"),
        Transition("filed", "ack_overdue", "followup_pending"),
        Transition("filed", "disposition_overdue", "followup_pending"),
        # 370.9(b) status letters are owed whether or not the carrier ever acknowledged.
        Transition("filed", "status_overdue", "followup_pending"),
        Transition("acknowledged", "disposition_overdue", "followup_pending"),
        Transition("acknowledged", "status_overdue", "followup_pending"),
        Transition("followup_pending", "acknowledged", "acknowledged"),
        Transition("followup_pending", "followup_sent_unacknowledged", "filed"),
        Transition("followup_pending", "followup_sent_acknowledged", "acknowledged"),
        Transition("filed", "resolved", "resolved"),
        Transition("acknowledged", "resolved", "resolved"),
        Transition("followup_pending", "resolved", "resolved"),
    ],
    terminal={"resolved"},
)

POLICY: dict[str, set[str]] = {
    "file_claim": {"ready"},
    "check_status": {"filed", "acknowledged", "followup_pending"},
    "draft_follow_up": {"followup_pending"},
}
