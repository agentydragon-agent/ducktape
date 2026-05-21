"""Geometric Brownian scalar exogenous models."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel


class GeometricBrownian(BaseModel):
    """Fixture GBM-sampled level process for one external series.

    `initial_value` is the month-0 level. Later months apply
    `exp(N(mu, sigma))` to the previous month's level. Sampling uses
    Each rollout uses its corresponding explicit request seed, so path
    identity is supplied by `ExogenousSamplingRequest` rather than model config.
    """

    kind: Literal["gbm"] = "gbm"
    initial_value: float
    monthly_log_return_mu: float = 0.0
    monthly_log_return_sigma: float = 0.0

    def sample_levels(self, *, rollout_seeds: tuple[int, ...], horizon_months: int) -> np.ndarray:
        rollout_count = len(rollout_seeds)
        levels = np.empty((rollout_count, horizon_months + 1), dtype=np.float64)
        levels[:, 0] = self.initial_value
        for rollout_index, seed in enumerate(rollout_seeds):
            rng = np.random.default_rng(seed)
            log_returns = rng.normal(
                loc=self.monthly_log_return_mu, scale=self.monthly_log_return_sigma, size=horizon_months
            )
            levels[rollout_index, 1:] = self.initial_value * np.exp(np.cumsum(log_returns))
        return levels
