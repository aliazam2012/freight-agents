"""Idempotency-Key handling as the IETF HTTPAPI draft describes it (version 09, read 2026-11-23).

The header value is a Structured Field String, so it arrives quoted. Each key is stored
with a fingerprint of its route and request: the same key and request replays the first
response; a missing or malformed key is 400, the same key with a different request 422,
and a key whose first request is still running 409, each as problem details (RFC 9457).
Keys expire after KEY_TTL, the expiry policy a resource is asked to publish.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

KEY_TTL = dt.timedelta(hours=24)
PROBLEM = "application/problem+json"
DOCS = "https://github.com/aliazam2012/freight-agents/tree/main/services"

Clock = Callable[[], dt.datetime]


class Problem(Exception):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(title)
        self.status, self.title, self.detail = status, title, detail


def install_problems(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def problem(_: Request, exc: Problem) -> JSONResponse:
        body = {"type": f"{DOCS}#idempotency", "title": exc.title, "status": exc.status,
                "detail": exc.detail}  # fmt: skip
        return JSONResponse(body, status_code=exc.status, media_type=PROBLEM)


def parse_key(header: str | None) -> str:
    if header is None:
        raise Problem(400, "Idempotency-Key is required", "Send a quoted key on every write.")
    value = header.strip()
    if len(value) < 3 or not (value.startswith('"') and value.endswith('"')):
        raise Problem(400, "Idempotency-Key must be a quoted string",
                      'Structured Field String, for example "8e03978e".')  # fmt: skip
    return value[1:-1]


class KeyStore:
    """Idempotency keys in SQLite, next to whatever the service stores."""

    def __init__(self, db: sqlite3.Connection, lock: threading.Lock, clock: Clock) -> None:
        self.db, self.lock, self.clock = db, lock, clock
        with self.lock, self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, request TEXT NOT NULL, "
                "created_at TEXT NOT NULL, status INTEGER, response TEXT)"
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
            self.db.execute("UPDATE keys SET status = ?, response = ? WHERE key = ?",
                            (status, json.dumps(response), key))  # fmt: skip

    def abandon(self, key: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM keys WHERE key = ? AND status IS NULL", (key,))

    def run(
        self, key: str, route: str, request: str, work: Callable[[], BaseModel], status: int
    ) -> JSONResponse:
        """Do `work` once for this key; a retry with the same request gets the same answer."""
        replay = self.begin(key, route, request)
        if replay is not None:
            return JSONResponse(replay[1], status_code=replay[0])
        try:
            out = work()
        except Exception:
            self.abandon(key)
            raise
        body = out.model_dump(mode="json")
        self.finish(key, status, body)
        return JSONResponse(body, status_code=status)
