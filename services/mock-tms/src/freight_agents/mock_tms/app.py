"""A made-up TMS order API. It exists so the tms-orders app has a real HTTP write to make safe.

Writes take an ``Idempotency-Key`` header as the IETF HTTPAPI draft describes it
(draft-ietf-httpapi-idempotency-key-header-09, read 2026-11-23): the value is a
Structured Field String, so it arrives quoted. The server stores a fingerprint of
each request with its key:

* the same key and the same request replays the first response;
* a missing or malformed key is 400, the same key with a different request is 422,
  and a key whose first request is still running is 409, each as problem details
  (RFC 9457);
* keys are kept for 24 hours (KEY_TTL), the expiry policy the draft asks a
  resource to publish.

State lives in SQLite (in memory by default), so a demo can keep orders between runs.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from freight_agents.mock_kit.idempotency import (
    KEY_TTL,
    KeyStore,
    Problem,
    install_problems,
    parse_key,
)
from pydantic import BaseModel

__all__ = ["KEY_TTL", "OrderIn", "OrderOut", "OrderPatch", "create_app"]


Clock = Callable[[], dt.datetime]


class OrderIn(BaseModel):
    fingerprint: str
    tender_reference: str
    order: dict[str, Any]


class OrderPatch(BaseModel):
    action: Literal["change", "cancel"]
    tender_reference: str
    order: dict[str, Any] | None


class OrderOut(BaseModel):
    order_id: str
    status: Literal["open", "cancelled"]
    version: int
    fingerprint: str
    tender_reference: str
    order: dict[str, Any]
    created_at: dt.datetime
    updated_at: dt.datetime


class Store:
    """Orders and idempotency keys in one SQLite database, behind one lock."""

    def __init__(self, path: str, clock: Clock) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.clock = clock
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY, body TEXT NOT NULL, fingerprint TEXT NOT NULL);
            """
        )
        self.keys = KeyStore(self.db, self.lock, clock)

    def create(self, body: OrderIn) -> OrderOut:
        with self.lock, self.db:
            count = self.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            now = self.clock()
            out = OrderOut(order_id=f"ORD-{count + 1:06d}", status="open", version=1,
                           fingerprint=body.fingerprint, tender_reference=body.tender_reference,
                           order=body.order, created_at=now, updated_at=now)  # fmt: skip
            self.db.execute("INSERT INTO orders VALUES (?, ?, ?)",
                            (out.order_id, out.model_dump_json(), out.fingerprint))  # fmt: skip
            return out

    def get(self, order_id: str) -> OrderOut | None:
        row = self.db.execute("SELECT body FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return OrderOut.model_validate_json(row[0]) if row else None

    def find(self, fingerprint: str | None) -> list[OrderOut]:
        rows = self.db.execute("SELECT body FROM orders ORDER BY order_id").fetchall()
        orders = [OrderOut.model_validate_json(r[0]) for r in rows]
        return [o for o in orders if fingerprint is None or o.fingerprint == fingerprint]

    def save(self, out: OrderOut) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE orders SET body = ? WHERE order_id = ?",
                            (out.model_dump_json(), out.order_id))  # fmt: skip


def create_app(clock: Clock | None = None, db: str | Path = ":memory:") -> FastAPI:
    app = FastAPI(
        title="Mock TMS",
        version="0.1.0",
        description="A made-up TMS order API with Idempotency-Key semantics.",
    )
    store = Store(str(db), clock or (lambda: dt.datetime.now(dt.UTC)))
    app.state.store = store

    install_problems(app)

    @app.post("/orders", status_code=201, response_model=OrderOut)
    def create_order(
        body: OrderIn, idempotency_key: str | None = Header(default=None)
    ) -> JSONResponse:
        key = parse_key(idempotency_key)
        return store.keys.run(key, "POST /orders", body.model_dump_json(),
                          lambda: store.create(body), 201)  # fmt: skip

    @app.get("/orders", response_model=list[OrderOut])
    def list_orders(fingerprint: str | None = None) -> list[OrderOut]:
        return store.find(fingerprint)

    @app.get("/orders/{order_id}", response_model=OrderOut)
    def get_order(order_id: str) -> OrderOut:
        found = store.get(order_id)
        if found is None:
            raise HTTPException(404, f"no order {order_id}")
        return found

    @app.patch("/orders/{order_id}", response_model=OrderOut)
    def patch_order(
        order_id: str, body: OrderPatch, idempotency_key: str | None = Header(default=None)
    ) -> JSONResponse:
        key = parse_key(idempotency_key)

        def work() -> OrderOut:
            found = store.get(order_id)
            if found is None:
                raise HTTPException(404, f"no order {order_id}")
            if found.status == "cancelled":
                raise Problem(422, "The order is cancelled", "A cancelled order cannot change.")
            update: dict[str, Any] = {"version": found.version + 1,
                                      "tender_reference": body.tender_reference,
                                      "updated_at": store.clock()}  # fmt: skip
            if body.action == "cancel":
                update["status"] = "cancelled"
            elif body.order is not None:
                update["order"] = body.order
            out = found.model_copy(update=update)
            store.save(out)
            return out

        return store.keys.run(key, f"PATCH /orders/{order_id}", body.model_dump_json(), work, 200)

    return app


def write_openapi(path: Path) -> None:
    path.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    write_openapi(Path(__file__).resolve().parents[3] / "openapi.json")
