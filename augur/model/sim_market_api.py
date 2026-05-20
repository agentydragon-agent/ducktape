"""Shared API for market models consumed by `augur/sim`."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import polars as pl

MARKET_PRICES_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "asset_id": pl.Utf8(), "price_per_unit_usd": pl.Float64()}
)


class ScalarMarketModel(Protocol):
    """One market's marginal model, used inside independent compositions."""

    def sample_prices(self, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        """Return prices shaped `(rollout_count, horizon_months + 1)`."""
        ...


class JointMarketModel(Protocol):
    """Joint market model API consumed by the simulator."""

    def materialize(self, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
        """Return all modeled markets as a `MARKET_PRICES_SCHEMA` frame."""
        ...


def market_prices_frame(asset_id: str, prices: np.ndarray, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    if prices.shape != expected_shape:
        raise ValueError(f"market {asset_id!r} produced prices with shape {prices.shape}; expected {expected_shape}")

    rollout_idx = np.repeat(np.arange(rollout_count, dtype=np.int64), horizon_months + 1)
    month_idx = np.tile(np.arange(horizon_months + 1, dtype=np.int64), rollout_count)
    return pl.DataFrame(
        {
            "rollout_index": rollout_idx,
            "month_index": month_idx,
            "asset_id": [asset_id] * (rollout_count * (horizon_months + 1)),
            "price_per_unit_usd": prices.reshape(-1),
        },
        schema=MARKET_PRICES_SCHEMA,
    )
