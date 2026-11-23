"""Durable stores the safety hooks rely on: approvals, idempotency keys, audit.

Each is a single SQLite table. ``":memory:"`` gives a throwaway store for
tests; a file path gives one that survives restarts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def args_hash(tool: str, case_id: str | None, args: dict[str, Any]) -> str:
    body = json.dumps(
        {"tool": tool, "case": case_id, "args": args},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("pragma journal_mode=wal")
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Approval:
    id: str
    tool: str
    case_id: str | None
    args: dict[str, Any]
    status: str


class ApprovalQueue:
    """Requests for a person to approve one exact call. An approval is used once."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._db = _connect(path)
        self._db.execute(
            """create table if not exists approvals (
                id text primary key,
                tool text not null,
                case_id text,
                args_hash text not null,
                args_json text not null,
                status text not null check (status in ('pending', 'approved', 'used', 'rejected')),
                requested_at text not null,
                decided_by text,
                decided_at text
            )"""
        )

    def request(self, tool: str, args: dict[str, Any], case_id: str | None) -> str:
        key = args_hash(tool, case_id, args)
        row = self._db.execute(
            "select id from approvals where args_hash = ? and status = 'pending'", (key,)
        ).fetchone()
        if row:
            return str(row[0])
        approval_id = f"apr_{uuid.uuid4().hex[:12]}"
        self._db.execute(
            "insert into approvals (id, tool, case_id, args_hash, args_json, status, requested_at)"
            " values (?, ?, ?, ?, ?, 'pending', ?)",
            (approval_id, tool, case_id, key, json.dumps(args, default=str), _now()),
        )
        return approval_id

    def approve(self, approval_id: str, approver: str) -> None:
        self._decide(approval_id, approver, "approved")

    def reject(self, approval_id: str, approver: str) -> None:
        self._decide(approval_id, approver, "rejected")

    def _decide(self, approval_id: str, approver: str, status: str) -> None:
        changed = self._db.execute(
            "update approvals set status = ?, decided_by = ?, decided_at = ?"
            " where id = ? and status = 'pending'",
            (status, approver, _now(), approval_id),
        ).rowcount
        if not changed:
            raise LookupError(f"no pending approval {approval_id}")

    def use(self, tool: str, args: dict[str, Any], case_id: str | None) -> bool:
        """Consume an approval for exactly this call, if one is waiting."""
        key = args_hash(tool, case_id, args)
        changed = self._db.execute(
            "update approvals set status = 'used' where id = ("
            " select id from approvals where args_hash = ? and status = 'approved' limit 1)",
            (key,),
        ).rowcount
        return bool(changed)

    def release(self, approval_id: str) -> None:
        """Hand a used approval back when the approved call failed, so it can be retried."""
        self._db.execute(
            "update approvals set status = 'approved' where id = ? and status = 'used'",
            (approval_id,),
        )

    def status(self, approval_id: str) -> str:
        row = self._db.execute(
            "select status from approvals where id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no approval {approval_id}")
        return str(row[0])

    def get(self, approval_id: str) -> Approval:
        row = self._db.execute(
            "select id, tool, case_id, args_json, status from approvals where id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"no approval {approval_id}")
        return Approval(row[0], row[1], row[2], json.loads(row[3]), row[4])

    def pending(self) -> list[Approval]:
        rows = self._db.execute(
            "select id from approvals where status = 'pending' order by requested_at"
        ).fetchall()
        return [self.get(r[0]) for r in rows]


class IdempotencyStore:
    """The first output of each write, keyed by tool, case and arguments."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._db = _connect(path)
        self._db.execute(
            "create table if not exists done (key text primary key, output_json text not null,"
            " at text not null)"
        )

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._db.execute("select output_json from done where key = ?", (key,)).fetchone()
        return None if row is None else dict(json.loads(row[0]))

    def put(self, key: str, output: dict[str, Any]) -> None:
        self._db.execute(
            "insert or ignore into done (key, output_json, at) values (?, ?, ?)",
            (key, json.dumps(output, default=str), _now()),
        )


class AuditLog:
    """One row per tool call, whatever happened to it."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._db = _connect(path)
        self._db.execute(
            """create table if not exists audit (
                at text not null,
                run_id text not null,
                agent text not null,
                case_id text,
                tool text not null,
                args_hash text not null,
                status text not null,
                code text
            )"""
        )

    def rows(self, tool: str | None = None) -> list[dict[str, Any]]:
        query = "select at, run_id, agent, case_id, tool, args_hash, status, code from audit"
        params: tuple[str, ...] = ()
        if tool is not None:
            query, params = query + " where tool = ?", (tool,)
        names = ("at", "run_id", "agent", "case_id", "tool", "args_hash", "status", "code")
        return [dict(zip(names, row, strict=True)) for row in self._db.execute(query, params)]

    def record(
        self,
        *,
        run_id: str,
        agent: str,
        case_id: str | None,
        tool: str,
        args: dict[str, Any],
        status: str,
        code: str | None,
    ) -> None:
        self._db.execute(
            "insert into audit values (?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), run_id, agent, case_id, tool, args_hash(tool, case_id, args), status, code),
        )
