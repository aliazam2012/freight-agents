"""Deterministic graders. A model-as-judge grader is added only where no rule can grade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MONEY_TOLERANCE = 0.01


def values_equal(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return abs(float(expected) - float(actual)) <= MONEY_TOLERANCE
    return " ".join(str(expected).split()).casefold() == " ".join(str(actual).split()).casefold()


def field_matches(expected: Mapping[str, Any], actual: Mapping[str, Any] | None) -> tuple[int, int]:
    """(matched, total) over the fields the golden case names."""
    if actual is None:
        return 0, len(expected)
    matched = sum(1 for key, value in expected.items() if values_equal(value, actual.get(key)))
    return matched, len(expected)
