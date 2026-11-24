"""Shared test world for tms-orders: fixtures written, a mock TMS, and the workflow."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from freight_agents.mock_tms.app import create_app
from freight_agents.tms_orders.fixtures import write_fixtures
from freight_agents.tms_orders.tms import CircuitBreaker, HttpTms, fingerprint
from freight_agents.tms_orders.workflow import (
    OrdersIntake,
    Stores,
    load_locations,
    reference_models,
)

NOW = dt.datetime(2026, 11, 23, 12, 0, tzinfo=dt.UTC)


class World:
    def __init__(self, root: Path) -> None:
        self.tenders = root / "tenders"
        write_fixtures(self.tenders)
        self.gold = {
            g["id"]: g
            for g in map(json.loads, (self.tenders / "gold.jsonl").read_text().splitlines())
        }
        clock = lambda: NOW  # noqa: E731
        self.tms = HttpTms(TestClient(create_app()), breaker=CircuitBreaker(clock=clock),
                           sleep=lambda s: None, clock=clock)  # fmt: skip
        self.stores = Stores.at(root / "state")
        self.intake = OrdersIntake(
            stores=self.stores, tms=self.tms,
            models=reference_models(self.tenders / "gold.jsonl"),
            locations=load_locations(self.tenders / "locations.json"), clock=clock,
        )  # fmt: skip

    def path(self, case: str) -> Path:
        return self.tenders / self.gold[case]["file"]

    def kind(self, kind: str, source: str) -> str:
        return next(i for i, g in self.gold.items() if g["kind"] == kind and g["source"] == source)

    def orders(self, case: str) -> list[Any]:
        from freight_agents.tms_orders.domain import Tender

        return self.tms.find(fingerprint(Tender.model_validate(self.gold[case]["tender"]).order))
