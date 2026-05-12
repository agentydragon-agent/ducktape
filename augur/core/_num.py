"""Small numeric helpers shared across the deterministic and personal-wealth
simulators. Keeps the cross-cutting `finite_or` / `require_finite` guards in
one place instead of copy-pasted across three modules."""

from __future__ import annotations

import math
from typing import Any


def finite_or(value: Any, fallback: float) -> float:
    """Return `float(value)` when finite, else `fallback`. Tolerant of None /
    non-numeric inputs (returns `fallback`)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def require_finite(value: Any, label: str) -> float:
    """Return `float(value)` when finite; raise `ValueError` with `label`
    in the message otherwise. Used at boundaries where a missing/NaN value
    is a programming bug, not a recoverable condition."""
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Missing required numeric model value: {label}") from error
    if not math.isfinite(number):
        raise ValueError(f"Missing required numeric model value: {label}")
    return number
