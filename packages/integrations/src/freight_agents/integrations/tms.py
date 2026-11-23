"""The transport management system, as the agents see it: look up a shipment."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class Shipment(BaseModel):
    pro_number: str
    bol_number: str
    carrier: str
    shipper: str
    consignee: str
    ship_date: date
    delivery_date: date | None
    commodity: str
    declared_value_usd: float
    pieces: int
    weight_lb: float


class TmsClient(Protocol):
    def get_shipment(self, pro_number: str) -> Shipment | None: ...

    def find_by_bol(self, bol_number: str) -> Shipment | None: ...


def _key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


class FixtureTms:
    """Shipments from a JSON file; PRO and BOL lookups ignore case and punctuation."""

    def __init__(self, path: Path) -> None:
        rows = json.loads(path.read_text(encoding="utf-8"))
        self._shipments = [Shipment.model_validate(r) for r in rows]

    def get_shipment(self, pro_number: str) -> Shipment | None:
        key = _key(pro_number)
        return next((s for s in self._shipments if _key(s.pro_number) == key), None)

    def find_by_bol(self, bol_number: str) -> Shipment | None:
        key = _key(bol_number)
        return next((s for s in self._shipments if _key(s.bol_number) == key), None)
