"""Three ways to file a claim, behind one interface, each exactly once in its own way.

* ApiChannel: an Idempotency-Key derived from the claim, kept across retries, on the
  shared resilient HTTP layer; the carrier is searched by reference first, so a
  rerun after a crash finds the earlier filing.
* PortalChannel: portals take no keys, so the "my claims" list is searched before any
  submit, and a filing counts only when the confirmation page shows a claim number.
  A session that expires, or a form missing a field, fails before anything is filed.
* EmailChannel: the sent mail is the record; the claim is sent once and found again
  by its reference. The carrier's claim number arrives later, by reply.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from email import message_from_bytes
from pathlib import Path
from typing import Any, Literal, Protocol

from freight_agents.carrier_filing.domain import Carrier, ClaimPacket, FilingReceipt
from freight_agents.carrier_filing.packet import cover_letter
from freight_agents.integrations.http import HttpClient, ResilientHttp
from freight_agents.integrations.transport import Transport
from pydantic import BaseModel

Clock = Callable[[], dt.datetime]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class CarrierStatus(BaseModel):
    claim_number: str
    status: Literal["received", "acknowledged", "resolved"]
    acknowledged_on: dt.date | None
    disposition: Literal["paid", "declined", "offered"] | None
    disposition_amount: float | None
    disposition_on: dt.date | None


class CarrierChannel(Protocol):
    def find(self, reference: str) -> FilingReceipt | None: ...

    def file(self, packet: ClaimPacket, documents: list[Path]) -> FilingReceipt: ...


class PortalError(RuntimeError):
    """The portal did not confirm a filing; nothing counts as filed."""


def _claim_body(packet: ClaimPacket, documents: list[Path]) -> dict[str, Any]:
    f = packet.fields
    return {
        "reference": packet.reference,
        "claimant": f.claimant_name or "",
        "pro_number": f.pro_number,
        "bol_number": f.bol_number,
        "claim_type": f.claim_type,
        "description": f.damage_description or "",
        "amount_usd": f.claimed_amount_usd,
        "documents": [d.name for d in documents] + [d.name for d in packet.documents],
    }


class ApiChannel(ResilientHttp):
    def __init__(self, client: HttpClient, carrier: Carrier, **kwargs: Any) -> None:
        super().__init__(client, service=carrier.name, **kwargs)
        self.carrier = carrier

    def _receipt(self, claim: dict[str, Any]) -> FilingReceipt:
        return FilingReceipt(
            carrier_claim_number=claim["claim_number"],
            channel="api",
            reference=claim["reference"],
            received_on=dt.date.fromisoformat(claim["received_on"]),
        )

    def find(self, reference: str) -> FilingReceipt | None:
        found = self.send("GET", "/api/claims", params={"reference": reference}).json()
        return self._receipt(found[0]) if found else None

    def file(self, packet: ClaimPacket, documents: list[Path]) -> FilingReceipt:
        cover_letter(packet)  # refuses a packet missing a 370.3 element
        existing = self.find(packet.reference)
        if existing is not None:
            return existing
        key = f"claim:{self.carrier.scac}:{packet.reference}"
        response = self.send("POST", "/api/claims", json=_claim_body(packet, documents), key=key)
        return self._receipt(response.json())

    def status(self, receipt: FilingReceipt) -> CarrierStatus | None:
        claim = self.send("GET", f"/api/claims/{receipt.carrier_claim_number}").json()
        return CarrierStatus(
            claim_number=claim["claim_number"],
            status=claim["status"],
            acknowledged_on=claim["acknowledged_on"],
            disposition=claim["disposition"],
            disposition_amount=claim["disposition_amount"],
            disposition_on=claim["disposition_on"],
        )


FORM_FIELDS = [
    "reference",
    "claimant",
    "pro_number",
    "bol_number",
    "claim_type",
    "description",
    "amount_usd",
]
CLAIM_NUMBER = re.compile(r"Claim number: (\S+)")
RECEIVED = re.compile(r"Received on (\d{4}-\d{2}-\d{2})")
DATED = re.compile(r"^Date: (\d{4}-\d{2}-\d{2})$", re.MULTILINE)


class PortalChannel:
    def __init__(
        self,
        carrier: Carrier,
        user: str,
        password: str,
        *,
        base_url: str | None = None,
        timeout_ms: float = 10_000,
        on_form_filled: Callable[[], None] | None = None,
    ) -> None:
        self.carrier, self.user, self.password = carrier, user, password
        self.base = (base_url or carrier.endpoint.removesuffix("/portal")).rstrip("/")
        self.timeout_ms = timeout_ms
        self.on_form_filled = on_form_filled

    def _run[T](self, work: Callable[[Any], T]) -> T:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(f"{self.base}/portal/login")
                page.fill("#username", self.user)
                page.fill("#password", self.password)
                page.click("#sign-in")
                page.wait_for_load_state()
                if page.locator("#error").count():
                    raise PortalError("the portal refused the sign-in")
                return work(page)
            finally:
                browser.close()

    def _find_on(self, page: Any, reference: str) -> FilingReceipt | None:
        page.goto(f"{self.base}/portal/claims")
        for row in page.locator("#claims tr").all()[1:]:
            if row.locator("td.reference").inner_text().strip() == reference:
                return FilingReceipt(
                    carrier_claim_number=row.locator("td.number").inner_text().strip(),
                    channel="portal",
                    reference=reference,
                    received_on=dt.date.fromisoformat(row.locator("td.received").inner_text()),
                )
        return None

    def find(self, reference: str) -> FilingReceipt | None:
        return self._run(lambda page: self._find_on(page, reference))

    def file(self, packet: ClaimPacket, documents: list[Path]) -> FilingReceipt:
        values = {
            k: "" if v is None else str(v)
            for k, v in _claim_body(packet, []).items()
            if k in FORM_FIELDS
        }

        def work(page: Any) -> FilingReceipt:
            existing = self._find_on(page, packet.reference)
            if existing is not None:
                return existing
            page.goto(f"{self.base}/portal/claims/new")
            for name in FORM_FIELDS:
                field = page.locator(f"#{name}")
                if field.count() == 0:
                    raise PortalError(f"the claim form has no {name} field; nothing was filed")
                if name == "claim_type":
                    field.select_option(values[name])
                else:
                    field.fill(values[name])
            if documents:
                page.set_input_files("#documents", [str(d) for d in documents])
            if self.on_form_filled is not None:
                self.on_form_filled()
            page.click("#submit-claim")
            page.wait_for_load_state()
            if page.url.rstrip("/").endswith("/portal/login"):
                raise PortalError("the portal session expired before the claim was submitted")
            text = page.inner_text("body")  # rendered text, as a person reads the page
            number, received = CLAIM_NUMBER.search(text), RECEIVED.search(text)
            if number is None or received is None:
                raise PortalError("no confirmation with a claim number; nothing counts as filed")
            return FilingReceipt(
                carrier_claim_number=number.group(1),
                channel="portal",
                reference=packet.reference,
                received_on=dt.date.fromisoformat(received.group(1)),
            )

        cover_letter(packet)  # refuses a packet missing a 370.3 element
        return self._run(work)


class EmailChannel:
    def __init__(
        self,
        carrier: Carrier,
        transport: Transport,
        *,
        sender: str,
        outbox: Path,
        clock: Clock = _now,
    ) -> None:
        self.carrier, self.transport, self.sender = carrier, transport, sender
        self.outbox, self.clock = outbox, clock

    def _subject(self, reference: str) -> str:
        return f"Freight claim {reference} for {self.carrier.name}"

    def find(self, reference: str) -> FilingReceipt | None:
        subject = self._subject(reference)
        for path in sorted(self.outbox.glob("*.eml")) if self.outbox.exists() else []:
            message = message_from_bytes(path.read_bytes())
            if message["Subject"] == subject and message["To"] == self.carrier.endpoint:
                dated = DATED.search(str(message.get_payload()))
                if dated is None:
                    continue
                sent = dt.date.fromisoformat(dated.group(1))
                return FilingReceipt(
                    carrier_claim_number=f"pending:{message['Message-ID']}",
                    channel="email",
                    reference=reference,
                    received_on=sent,
                )
        return None

    def compose(self, packet: ClaimPacket) -> dict[str, str]:
        """The exact message a person approves and the channel then sends."""
        letter = cover_letter(packet)
        body = f"Date: {self.clock().date().isoformat()}\n\n{letter}"
        return {
            "to": self.carrier.endpoint,
            "subject": self._subject(packet.reference),
            "body": body,
        }

    def send(self, reference: str, message: dict[str, str]) -> FilingReceipt:
        """Send an approved message once; a second call finds the first."""
        existing = self.find(reference)
        if existing is not None:
            return existing
        message_id = self.transport.send(
            sender=self.sender, to=message["to"], subject=message["subject"], body=message["body"]
        )
        return FilingReceipt(
            carrier_claim_number=f"pending:{message_id}",
            channel="email",
            reference=reference,
            received_on=self.clock().date(),
        )

    def file(self, packet: ClaimPacket, documents: list[Path]) -> FilingReceipt:
        return self.send(packet.reference, self.compose(packet))
