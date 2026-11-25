import datetime as dt
from pathlib import Path

import pytest
from freight_agents.carrier_filing.domain import (
    CARRIERS,
    ClaimPacket,
    carrier_for,
    from_claims_case,
)
from freight_agents.carrier_filing.packet import cover_letter, write_cover_letter
from freight_agents.claims_intake.domain import ClaimFields

FIELDS = ClaimFields(
    pro_number="7741-2209",
    bol_number="BOL-55102",
    carrier="Example Motor Express",
    ship_date=dt.date(2026, 11, 2),
    delivery_date=dt.date(2026, 11, 9),
    commodity="dining chairs",
    claim_type="damage",
    damage_description="4 of 12 chairs arrived with broken legs",
    claimed_amount_usd=640.0,
    claimant_name="Larkspur Home Goods",
    claimant_email="claims@lhg.example.com",
    photo_count=3,
)


def test_one_carrier_per_channel() -> None:
    assert {c.channel for c in CARRIERS} == {"api", "portal", "email"}
    assert carrier_for("Example Motor Express").channel == "portal"
    with pytest.raises(KeyError):
        carrier_for("Unknown Lines")


def test_a_handed_off_claims_case_becomes_a_packet() -> None:
    packet = from_claims_case("claim-001", {"fields": FIELDS.model_dump(mode="json")})
    assert packet.carrier.scac == carrier_for("Example Motor Express").scac
    assert packet.missing() == []
    assert packet.reference == "claim-001"


def test_a_packet_missing_a_370_3_element_is_refused() -> None:
    fields = FIELDS.model_copy(update={"claimed_amount_usd": None})
    packet = ClaimPacket(
        reference="claim-002",
        carrier=carrier_for("Example Freight Lines"),
        fields=fields,
        documents=[],
    )
    assert packet.missing() == ["amount"]
    with pytest.raises(ValueError, match="amount"):
        cover_letter(packet)


def test_the_cover_letter_names_every_370_3_element(tmp_path: Path) -> None:
    packet = from_claims_case("claim-001", {"fields": FIELDS.model_dump(mode="json")})
    text = cover_letter(packet)
    for needed in (
        "7741-2209",
        "BOL-55102",
        "damage",
        "broken legs",
        "$640.00",
        "49 CFR 370.3",
        "Larkspur Home Goods",
    ):
        assert needed in text
    path = write_cover_letter(packet, tmp_path / "cover.pdf")
    from freight_agents.integrations.documents import pdf_text

    assert "7741-2209" in pdf_text(path)
