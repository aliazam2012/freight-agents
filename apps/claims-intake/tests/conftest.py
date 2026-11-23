import json
from datetime import UTC, datetime
from email.message import EmailMessage as Mime
from pathlib import Path
from typing import Any

import pytest
from freight_agents.claims_intake.workflow import ClaimsIntake, Stores
from freight_agents.integrations.email import EmailMessage, parse_eml
from freight_agents.integrations.tms import FixtureTms
from freight_agents.llm import ModelTurn, ScriptedModel, ToolCall, Usage

SHIPMENT = {
    "pro_number": "7741-2209",
    "bol_number": "BOL-55102",
    "carrier": "Example Freight Lines",
    "shipper": "Larkspur Home Goods",
    "consignee": "Harbor Street Furniture",
    "ship_date": "2026-11-02",
    "delivery_date": "2026-11-09",
    "commodity": "dining chairs",
    "declared_value_usd": 2400.0,
    "pieces": 12,
    "weight_lb": 640.0,
}

FIELDS: dict[str, Any] = {
    "pro_number": "7741-2209",
    "bol_number": None,
    "carrier": "Example Freight Lines",
    "ship_date": "2026-11-02",
    "delivery_date": "2026-11-09",
    "commodity": "dining chairs",
    "claim_type": "damage",
    "damage_description": "4 of 12 chairs arrived with broken legs",
    "claimed_amount_usd": 800.0,
    "claimant_name": "Dana Reyes",
    "claimant_email": "dana@example.com",
    "photo_count": 0,
}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def email(
    body: str, subject: str = "Damage claim PRO 7741-2209", attach: str | None = None
) -> EmailMessage:
    msg = Mime()
    msg["Message-ID"] = f"<{abs(hash((body, subject, attach)))}@example.com>"
    msg["From"] = "Dana Reyes <dana@example.com>"
    msg["To"] = "claims@example.org"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 16 Nov 2026 09:30:00 -0800"
    msg.set_content(body)
    if attach:
        msg.add_attachment(b"%PDF fake", maintype="application", subtype="pdf", filename=attach)
    return parse_eml(msg.as_bytes())


def turn(*calls: ToolCall, text: str = "") -> ModelTurn:
    return ModelTurn(
        text=text,
        tool_calls=list(calls),
        stop="tool_use" if calls else "end",
        usage=Usage(input_tokens=100, output_tokens=20),
        model="scripted",
    )


def call(name: str, **args: Any) -> ToolCall:
    return ToolCall(
        id=f"{name}-{abs(hash(json.dumps(args, sort_keys=True)))}", name=name, args=args
    )


def triage(label: str = "claim") -> list[ModelTurn]:
    return [turn(call("submit_triage", label=label, reason="test")), turn(text="done")]


def extraction(fields: dict[str, Any]) -> list[ModelTurn]:
    return [
        turn(call("lookup_shipment", pro_number="7741-2209", bol_number=None)),
        turn(call("save_claim_fields", fields=fields)),
        turn(text="saved"),
    ]


def draft(to: str = "dana@example.com") -> list[ModelTurn]:
    body = "Hello Dana, please send the amount you are claiming."
    return [
        turn(
            call("draft_info_request", to=to, missing=["amount"], subject="Your claim", body=body)
        ),
        turn(text="drafted"),
    ]


@pytest.fixture
def make_intake(tmp_path: Path):  # type: ignore[no-untyped-def]
    tms_path = tmp_path / "tms.json"
    tms_path.write_text(json.dumps([SHIPMENT]))

    def build(script: list[ModelTurn]) -> ClaimsIntake:
        clock = Clock()
        return ClaimsIntake(
            model=ScriptedModel(script),
            tms=FixtureTms(tms_path),
            stores=Stores.at(tmp_path / "state", clock),
            clock=clock,
        )

    return build
