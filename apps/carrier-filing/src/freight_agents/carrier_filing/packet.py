"""The claim's cover letter: the 49 CFR 370.3(b) elements, stated plainly, on one page.

370.3(b): a claim identifies the shipment, asserts the carrier's liability for the
loss or damage, and claims payment of a specified or determinable amount. The letter
states each, so a carrier cannot treat the filing as a mere notice of damage.
"""

from __future__ import annotations

from pathlib import Path

from freight_agents.carrier_filing.domain import ClaimPacket
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def cover_letter(packet: ClaimPacket) -> str:
    gaps = packet.missing()
    if gaps:
        raise ValueError(f"claim {packet.reference} is missing {', '.join(gaps)}")
    f = packet.fields
    ids = ", ".join(
        x
        for x in (
            f"PRO {f.pro_number}" if f.pro_number else "",
            f"bill of lading {f.bol_number}" if f.bol_number else "",
        )
        if x
    )
    lines = [
        f"To: {packet.carrier.name} ({packet.carrier.scac}), freight claims",
        f"From: {f.claimant_name or 'the claimant'}",
        f"Claim reference: {packet.reference}",
        "",
        "This is a claim for loss or damage under 49 CFR 370.3 and 49 U.S.C. 14706.",
        f"Shipment: {ids}; shipped {f.ship_date}, delivered {f.delivery_date}; {f.commodity}.",
        f"Liability: {f.claim_type}. {f.damage_description}. The carrier is liable for the "
        "actual loss or injury to the property.",
        f"Amount claimed: ${f.claimed_amount_usd:,.2f}.",
        "",
        "Enclosed: " + (", ".join(d.name for d in packet.documents) or "no documents"),
        "Please acknowledge this claim in writing within 30 days (49 CFR 370.5).",
    ]
    return "\n".join(lines)


def write_cover_letter(packet: ClaimPacket, path: Path) -> Path:
    page = canvas.Canvas(str(path), pagesize=LETTER, invariant=True)
    page.setTitle(f"Freight claim {packet.reference}")
    y = 740.0
    for text in cover_letter(packet).splitlines():
        page.setFont("Helvetica", 10)
        page.drawString(54, y, text)
        y -= 16
    page.showPage()
    page.save()
    return path
