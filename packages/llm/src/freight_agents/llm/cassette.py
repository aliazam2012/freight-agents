"""Record live model turns once, replay them offline forever.

A cassette is a JSON Lines file: one ``{"key": ..., "turn": ...}`` per request.
The key is a hash of everything the model saw except provider-native payloads,
so a replay matches when the conversation, system prompt and tools match.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .types import Message, Model, ModelTurn, ToolSpec


class CassetteMiss(LookupError):
    """No recorded turn for this request."""

    def __init__(self, key: str) -> None:
        super().__init__(f"no recorded turn for request {key[:12]}")
        self.key = key


def request_key(
    model_name: str, system: str, messages: list[Message], tools: list[ToolSpec]
) -> str:
    body = {
        "model": model_name,
        "system": system,
        "messages": [m.model_dump(mode="json", exclude={"native"}) for m in messages],
        "tools": [t.model_dump(mode="json") for t in tools],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecordingModel:
    """Passes each request to a live model and appends the turn to a cassette."""

    def __init__(self, inner: Model, path: Path) -> None:
        self._inner = inner
        self._path = path

    @property
    def name(self) -> str:
        return self._inner.name

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        turn = self._inner.complete(system, messages, tools)
        line = {
            "key": request_key(self.name, system, messages, tools),
            "turn": turn.model_dump(mode="json"),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        return turn


class ReplayModel:
    """Answers from a cassette; an unrecorded request raises CassetteMiss."""

    def __init__(self, path: Path, name: str) -> None:
        self._name = name
        self._turns: dict[str, ModelTurn] = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            # The first recording of a request wins, so a replay is deterministic.
            self._turns.setdefault(row["key"], ModelTurn.model_validate(row["turn"]))

    @property
    def name(self) -> str:
        return self._name

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        key = request_key(self._name, system, messages, tools)
        try:
            return self._turns[key]
        except KeyError:
            raise CassetteMiss(key) from None
