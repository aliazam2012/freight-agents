"""An append-only event store on SQLite.

Rows are never updated or deleted: triggers refuse it. Each case's events are
numbered from 1, and a writer must say which number it expects to write after,
so two writers racing on one case cannot both win.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class ConcurrencyError(RuntimeError):
    """Another writer appended to this case first."""


@dataclass(frozen=True)
class Event:
    case_id: str
    seq: int
    type: str
    payload: dict[str, Any]
    at: datetime
    actor: str


_SCHEMA = """
create table if not exists events (
    case_id text not null,
    seq integer not null,
    type text not null,
    payload text not null,
    at text not null,
    actor text not null,
    primary key (case_id, seq)
);
create trigger if not exists events_no_update before update on events
begin select raise(abort, 'events are append-only'); end;
create trigger if not exists events_no_delete before delete on events
begin select raise(abort, 'events are append-only'); end;
"""


class SqliteEventStore:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.executescript(_SCHEMA)

    def append(
        self,
        case_id: str,
        type: str,
        payload: dict[str, Any],
        *,
        actor: str,
        expected_seq: int,
        at: datetime,
    ) -> Event:
        seq = expected_seq + 1
        try:
            self._db.execute("begin immediate")
            (current,) = self._db.execute(
                "select coalesce(max(seq), 0) from events where case_id = ?", (case_id,)
            ).fetchone()
            if current != expected_seq:
                raise ConcurrencyError(f"case {case_id} is at event {current}, not {expected_seq}")
            self._db.execute(
                "insert into events values (?, ?, ?, ?, ?, ?)",
                (case_id, seq, type, json.dumps(payload, default=str), at.isoformat(), actor),
            )
            self._db.execute("commit")
        except BaseException:
            self._db.execute("rollback")
            raise
        return Event(case_id, seq, type, payload, at, actor)

    def events(self, case_id: str) -> list[Event]:
        rows = self._db.execute(
            "select case_id, seq, type, payload, at, actor from events"
            " where case_id = ? order by seq",
            (case_id,),
        ).fetchall()
        return [
            Event(r[0], r[1], r[2], json.loads(r[3]), datetime.fromisoformat(r[4]), r[5])
            for r in rows
        ]

    def case_ids(self) -> list[str]:
        rows = self._db.execute("select distinct case_id from events order by case_id").fetchall()
        return [r[0] for r in rows]
