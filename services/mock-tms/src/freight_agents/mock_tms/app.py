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
import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

KEY_TTL = dt.timedelta(hours=24)
PROBLEM = "application/problem+json"
DOCS = "https://github.com/aliazam2012/freight-agents/tree/main/services/mock-tms"

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


class Problem(Exception):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(title)
        self.status, self.title, self.detail = status, title, detail


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
            CREATE TABLE IF NOT EXISTS keys (
                key TEXT PRIMARY KEY, request TEXT NOT NULL, created_at TEXT NOT NULL,
                status INTEGER, response TEXT);
            """
        )

    def begin(self, key: str, route: str, request: str) -> tuple[int, dict[str, Any]] | None:
        """Claim a key; return the stored answer for a finished replay, or None to proceed."""
        fingerprint = hashlib.sha256(f"{route}\n{request}".encode()).hexdigest()
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM keys WHERE created_at < ?", ((self.clock() - KEY_TTL).isoformat(),)
            )
            row = self.db.execute(
                "SELECT request, status, response FROM keys WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO keys (key, request, created_at) VALUES (?, ?, ?)",
                    (key, fingerprint, self.clock().isoformat()),
                )
                return None
        stored, status, response = row
        if stored != fingerprint:
            raise Problem(422, "Idempotency-Key reused with a different request",
                          "A key may be used for one request only.")  # fmt: skip
        if status is None:
            raise Problem(409, "A request is outstanding for this Idempotency-Key",
                          "Retry after the first request finishes.")  # fmt: skip
        return int(status), json.loads(response)

    def finish(self, key: str, status: int, response: dict[str, Any]) -> None:
        with self.lock, self.db:
            self.db.execute(
                "UPDATE keys SET status = ?, response = ? WHERE key = ?",
                (status, json.dumps(response), key),
            )

    def abandon(self, key: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM keys WHERE key = ? AND status IS NULL", (key,))

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


def _key(header: str | None) -> str:
    if header is None:
        raise Problem(400, "Idempotency-Key is required", "Send a quoted key on every write.")
    value = header.strip()
    if len(value) < 3 or not (value.startswith('"') and value.endswith('"')):
        raise Problem(400, "Idempotency-Key must be a quoted string",
                      'Structured Field String, for example "8e03978e".')  # fmt: skip
    return value[1:-1]


def create_app(clock: Clock | None = None, db: str | Path = ":memory:") -> FastAPI:
    app = FastAPI(
        title="Mock TMS",
        version="0.1.0",
        description="A made-up TMS order API with Idempotency-Key semantics.",
    )
    store = Store(str(db), clock or (lambda: dt.datetime.now(dt.UTC)))
    app.state.store = store

    @app.exception_handler(Problem)
    async def problem(_: Request, exc: Problem) -> JSONResponse:
        body = {"type": f"{DOCS}#idempotency", "title": exc.title, "status": exc.status,
                "detail": exc.detail}  # fmt: skip
        return JSONResponse(body, status_code=exc.status, media_type=PROBLEM)

    def idempotent(key: str, route: str, request: str, work: Callable[[], OrderOut],
                   status: int) -> JSONResponse:  # fmt: skip
        replay = store.begin(key, route, request)
        if replay is not None:
            return JSONResponse(replay[1], status_code=replay[0])
        try:
            out = work()
        except Exception:
            store.abandon(key)
            raise
        body = out.model_dump(mode="json")
        store.finish(key, status, body)
        return JSONResponse(body, status_code=status)

    @app.post("/orders", status_code=201, response_model=OrderOut)
    def create_order(
        body: OrderIn, idempotency_key: str | None = Header(default=None)
    ) -> JSONResponse:
        key = _key(idempotency_key)
        return idempotent(key, "POST /orders", body.model_dump_json(),
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
        key = _key(idempotency_key)

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

        return idempotent(key, f"PATCH /orders/{order_id}", body.model_dump_json(), work, 200)

    return app


def write_openapi(path: Path) -> None:
    path.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    write_openapi(Path(__file__).resolve().parents[3] / "openapi.json")
