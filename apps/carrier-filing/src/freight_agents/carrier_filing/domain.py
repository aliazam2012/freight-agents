"""Carriers, claim packets and filing receipts.

The claim fields and the 49 CFR 370.3 minimum check come from claims-intake, the
step before filing, so the rule is written once. A packet is filed only when that
check finds nothing missing.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from freight_agents.claims_intake.domain import ClaimFields, missing_requirements
from pydantic import BaseModel

Channel = Literal["api", "portal", "email"]


class Carrier(BaseModel):
    scac: str
    name: str
    channel: Channel
    endpoint: str  # API base URL, portal URL, or the claims mailbox


# Made-up carriers, checked in docs/NAMES.md; one per filing channel.
CARRIERS = [
    Carrier(
        scac="EXFL", name="Example Freight Lines", channel="api", endpoint="http://carrier.test/api"
    ),
    Carrier(
        scac="EXME",
        name="Example Motor Express",
        channel="portal",
        endpoint="http://carrier.test/portal",
    ),
    Carrier(
        scac="EXTL", name="Example Truck Lines", channel="email", endpoint="claims@extl.example.com"
    ),
]


def carrier_for(name: str) -> Carrier:
    for carrier in CARRIERS:
        if carrier.name.lower() == name.strip().lower() or carrier.scac == name.strip().upper():
            return carrier
    raise KeyError(f"no filing channel known for carrier {name!r}")


class Document(BaseModel):
    kind: Literal["bill_of_lading", "delivery_receipt", "invoice", "photo", "cover_letter"]
    name: str


class ClaimPacket(BaseModel):
    reference: str  # the claimant's claim id; the carrier's own number comes back on filing
    carrier: Carrier
    fields: ClaimFields
    documents: list[Document]

    def missing(self) -> list[str]:
        return missing_requirements(self.fields)


class FilingReceipt(BaseModel):
    carrier_claim_number: str  # "pending:<message id>" for email until the carrier answers
    channel: Channel
    reference: str
    received_on: dt.date  # the day the carrier received the claim; 370.5 and 370.9 count from it


def from_claims_case(case_id: str, data: dict[str, Any]) -> ClaimPacket:
    """A claims-intake case handed off for filing, as a packet for its carrier."""
    fields = ClaimFields.model_validate(data["fields"])
    if not fields.carrier:
        raise ValueError(f"case {case_id} names no carrier")
    documents = [
        Document(kind="photo", name=f"{case_id}-photo-{i + 1}.jpg")
        for i in range(fields.photo_count or 0)
    ]
    return ClaimPacket(
        reference=case_id, carrier=carrier_for(fields.carrier), fields=fields, documents=documents
    )
