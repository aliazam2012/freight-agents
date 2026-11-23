"""Untrusted values: anything that came from outside (an email, an attachment).

A value is tainted when it equals, contains, or is contained in a value
registered as untrusted, compared without case and with whitespace collapsed.
Hooks use this to stop untrusted text from steering a write or a send.
"""

from __future__ import annotations

import re

_SPACE = re.compile(r"\s+")
# Shorter fragments match too much ordinary text to mean anything.
MIN_FRAGMENT = 6


def _norm(value: str) -> str:
    return _SPACE.sub(" ", value).strip().lower()


class TaintSet:
    def __init__(self) -> None:
        self._values: dict[str, set[str]] = {}

    def add(self, value: str, source: str) -> None:
        norm = _norm(value)
        if norm:
            self._values.setdefault(norm, set()).add(source)

    def tainted(self, value: str) -> bool:
        return bool(self.sources(value))

    def sources(self, value: str) -> set[str]:
        norm = _norm(value)
        if len(norm) < MIN_FRAGMENT:
            return set(self._values.get(norm, set()))
        found: set[str] = set()
        for known, sources in self._values.items():
            if norm == known or norm in known or (len(known) >= MIN_FRAGMENT and known in norm):
                found |= sources
        return found
