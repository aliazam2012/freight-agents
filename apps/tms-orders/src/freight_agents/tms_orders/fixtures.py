"""Write the tender fixtures: gold.jsonl plus one file per tender in its own format.

Email tenders are .eml messages. EDI 204 files and PDF rate confirmations are
added by the EDI and PDF modules as they are built; each gold line names the
file its tender lives in.
"""

from __future__ import annotations

import json
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from freight_agents.tms_orders.domain import Source
from freight_agents.tms_orders.edi204 import write_204
from freight_agents.tms_orders.ratecon import render_pdf
from freight_agents.tms_orders.synth import Case, email_subject, generate, render_email

INBOX = "tenders@exfl.example.com"


def _email(case: Case) -> bytes:
    tender = case.tender
    prefix = tender.order.tender_id.split("-")[0].lower()
    message = EmailMessage()
    message["From"] = f"{tender.order.shipper.name} <transport@{prefix}.example.com>"
    message["To"] = INBOX
    message["Subject"] = email_subject(tender)
    message["Date"] = format_datetime(tender.received_at)
    message["Message-ID"] = tender.reference
    message.set_content(render_email(tender, style=case.style), cte="7bit")
    return bytes(message)


def _file(case: Case) -> str:
    if case.tender.source == Source.EMAIL:
        return f"email/{case.id}.eml"
    if case.tender.source == Source.EDI:
        return f"edi/{case.id}.edi"
    return f"pdf/{case.id}.pdf"


def write_fixtures(root: Path, seed: int = 11) -> list[Case]:
    cases = generate(seed=seed)
    for folder in ("email", "edi", "pdf"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    lines = []
    for case in cases:
        if case.tender.source == Source.EMAIL:
            (root / _file(case)).write_bytes(_email(case))
        elif case.tender.source == Source.EDI:
            # One segment per line, as most partners send it.
            (root / _file(case)).write_text(write_204(case.tender).replace("~", "~\n"))
        else:
            render_pdf(case.tender, case.style, root / _file(case))
        lines.append(
            json.dumps(
                {
                    "id": case.id,
                    "kind": case.kind,
                    "source": case.tender.source.value,
                    "style": case.style,
                    "file": _file(case),
                    "duplicate_of": case.duplicate_of,
                    "expected_rules": list(case.expected_rules),
                    "tender": case.tender.model_dump(mode="json"),
                },
                sort_keys=True,
            )
        )
    (root / "gold.jsonl").write_text("\n".join(lines) + "\n")
    return cases
