"""Deterministic scalar market models for `augur/sim`."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel


class Deterministic(BaseModel):
    """A fixed per-month price curve.

    `prices_usd` runs from month 0 through `horizon_months`
    inclusive; sampling validates that its length matches the
    requested horizon.
    """

    kind: Literal["deterministic"] = "deterministic"
    prices_usd: list[float]

    def sample_prices(self, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        expected = horizon_months + 1
        if len(self.prices_usd) != expected:
            msg = f"Deterministic model has {len(self.prices_usd)} prices; need {expected}"
            raise ValueError(msg)
        prices = np.asarray(self.prices_usd, dtype=np.float64)
        return np.tile(prices, (rollout_count, 1))


class Constant(BaseModel):
    """A constant price shared across every rollout and month."""

    kind: Literal["constant"] = "constant"
    price_usd: float

    def sample_prices(self, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        return np.full((rollout_count, horizon_months + 1), self.price_usd, dtype=np.float64)
