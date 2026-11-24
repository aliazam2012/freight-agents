"""One decision per tender: create, recognize a duplicate, change, cancel, or ask a person.

Exactly once comes from two layers. The TMS is searched by the load's fingerprint
before any write, so a resent tender or a rerun after a crash finds the order it
already made. Every write carries a key derived from the load (and, for changes,
the tender), so a reply lost in flight replays rather than repeats. Anything the
two cannot settle, such as a change for an order the TMS never saw, goes to review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from freight_agents.tms_orders.domain import Purpose, Tender
from freight_agents.tms_orders.tms import HttpTms, Receipt, fingerprint

Outcome = Literal["created", "duplicate", "changed", "cancelled", "needs_review"]


@dataclass(frozen=True)
class SubmitResult:
    outcome: Outcome
    receipt: Receipt | None
    reason: str


def submit(tms: HttpTms, tender: Tender) -> SubmitResult:
    fp = fingerprint(tender.order)
    existing = tms.find(fp)
    open_orders = [r for r in existing if r.status == "open"]

    if tender.purpose == Purpose.ORIGINAL:
        if open_orders:
            mine = [r for r in open_orders if r.tender_reference == tender.reference]
            if mine:
                return SubmitResult("created", mine[0], "recovered this tender's own earlier write")
            return SubmitResult("duplicate", open_orders[0], "an open order already has this load")
        if existing:
            return SubmitResult(
                "needs_review", None, "this load was cancelled; a person decides whether to rebook"
            )
        receipt = tms.create(tender.order, fp, tender.reference, key=f"create:{fp}")
        return SubmitResult("created", receipt, "")

    if not existing:
        return SubmitResult("needs_review", None, f"no order in the TMS for this {tender.purpose}")
    if tender.purpose == Purpose.CHANGE:
        if not open_orders:
            return SubmitResult("needs_review", None, "the order is cancelled; it cannot change")
        target = open_orders[0]
        receipt = tms.change(target.order_id, tender.order, tender.reference,
                             key=f"change:{fp}:{tender.reference}")  # fmt: skip
        return SubmitResult("changed", receipt, "")
    if not open_orders:
        return SubmitResult("cancelled", existing[0], "already cancelled")
    receipt = tms.cancel(open_orders[0].order_id, tender.reference,
                         key=f"cancel:{fp}:{tender.reference}")  # fmt: skip
    return SubmitResult("cancelled", receipt, "")
