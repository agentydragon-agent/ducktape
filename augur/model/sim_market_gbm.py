"""Geometric Brownian scalar market models for `augur/sim`."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel


class GeometricBrownian(BaseModel):
    """Fixture GBM-sampled level process for one market.

    `initial_value` is the month-0 level. Later months apply
    `exp(N(mu, sigma))` to the previous month's level. Sampling uses
    `numpy.random.default_rng(rng_seed)` so the same seed yields the
    same paths across runs.
    """

    kind: Literal["gbm"] = "gbm"
    initial_value: float
    monthly_log_return_mu: float = 0.0
    monthly_log_return_sigma: float = 0.0
    rng_seed: int = 0

    def sample_levels(self, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        rng = np.random.default_rng(self.rng_seed)
        log_returns = rng.normal(
            loc=self.monthly_log_return_mu, scale=self.monthly_log_return_sigma, size=(rollout_count, horizon_months)
        )
        cumulative = np.cumsum(log_returns, axis=1)
        levels = np.empty((rollout_count, horizon_months + 1), dtype=np.float64)
        levels[:, 0] = self.initial_value
        levels[:, 1:] = self.initial_value * np.exp(cumulative)
        return levels
