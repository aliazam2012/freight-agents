"""A scripted model for tests and offline demos."""

from __future__ import annotations

from dataclasses import dataclass

from .types import Message, ModelTurn, ToolSpec


class ScriptExhausted(RuntimeError):
    """The script has no turn left for this call."""


@dataclass(frozen=True)
class Call:
    system: str
    messages: list[Message]
    tools: list[ToolSpec]


class ScriptedModel:
    """Returns prepared turns in order and records every request it saw."""

    def __init__(self, turns: list[ModelTurn], name: str = "scripted") -> None:
        self._turns = list(turns)
        self._name = name
        self.calls: list[Call] = []

    @property
    def name(self) -> str:
        return self._name

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        self.calls.append(Call(system, list(messages), list(tools)))
        if not self._turns:
            raise ScriptExhausted(f"no scripted turn left for call {len(self.calls)}")
        return self._turns.pop(0)
