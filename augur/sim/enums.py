"""Simulation-wide IntEnum types for array-indexed discriminators.

These are IntEnum (not StrEnum) because the values index into numpy arrays
and must remain plain integers for arithmetic and indexing."""

from __future__ import annotations

from enum import IntEnum


class ObligationSource(IntEnum):
    CONFIGURED_OBLIGATION = 0
    MORTGAGE_PAYMENT = 1
    PROPERTY_TAX = 2
    ESTIMATED_TAX = 3
    ESTIMATED_TAX_Q4 = 4
    TAX_TRUE_UP = 5


class CapitalGainClassification(IntEnum):
    LONG_TERM = 0
    SHORT_TERM = 1


class LifecycleKind(IntEnum):
    FRACTION = 0
    CAPITAL_IMPROVEMENT = 1
    SALE = 2
