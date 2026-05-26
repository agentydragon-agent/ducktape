"""Compiler-wide shared helpers: integer-code sentinel, amount kinds,
StringTable, and the small `_slot`/`_amount_arrays`/`_empty_month_matrix`
utilities every per-domain compile function uses.

Lives alongside the per-domain compile modules under `augur/sim/compiler/`
so per-domain files can import these without pulling in the orchestrator
(`compiler/__init__.py`) and triggering a load-time cycle."""

from __future__ import annotations

from typing import Any

import numpy as np

from augur.sim.scenario import FixedAmount, SeriesIndexedAmount

NO_CODE = -1
AMOUNT_FIXED = 0
AMOUNT_SERIES_INDEXED = 1
ORDINARY_INCOME_CATEGORY = "ordinary"
ORDINARY_DEDUCTION_CATEGORY = "ordinary"


class StringTable:
    def __init__(self) -> None:
        self._by_value: dict[str, int] = {}
        self.values: list[str] = []

    def intern(self, value: str | None) -> int:
        if value is None:
            return NO_CODE
        existing = self._by_value.get(value)
        if existing is not None:
            return existing
        code = len(self.values)
        self._by_value[value] = code
        self.values.append(value)
        return code

    def require(self, value: str) -> int:
        return self.intern(value)


def slot(account_slot_by_key: dict[tuple[str, str], int], agent_id: str, account_id: str) -> int:
    return account_slot_by_key.get((agent_id, account_id), NO_CODE)


def amount_arrays(amount: Any, series_index_by_id: dict[str, int]) -> tuple[int, float, float, int, int, int]:
    if isinstance(amount, int | float):
        return AMOUNT_FIXED, float(amount), 0.0, NO_CODE, 0, 1
    if isinstance(amount, FixedAmount):
        return AMOUNT_FIXED, float(amount.amount_usd), 0.0, NO_CODE, 0, 1
    if isinstance(amount, SeriesIndexedAmount):
        return (
            AMOUNT_SERIES_INDEXED,
            0.0,
            float(amount.base_amount_usd),
            series_index_by_id[amount.series_id],
            int(amount.base_month_index),
            int(amount.adjustment_period_months),
        )
    raise TypeError(f"unsupported amount spec: {amount!r}")


def empty_month_matrix(months: int, slots: int, dtype: Any, fill: int | float = 0) -> np.ndarray:
    matrix = np.empty((months, max(1, slots)), dtype=dtype)
    matrix[...] = fill
    return matrix
