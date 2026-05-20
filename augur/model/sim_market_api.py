"""Shared API for market models consumed by `augur/sim`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import polars as pl

MARKET_LEVELS_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)
MARKET_EVENTS_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "event_id": pl.Utf8(), "active": pl.Boolean()}
)
MARKET_PRICES_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "asset_id": pl.Utf8(), "price_per_unit_usd": pl.Float64()}
)


@dataclass(frozen=True)
class MarketSamplingRequest:
    """Request metadata passed to a joint market model sample."""

    rollout_count: int
    horizon_months: int
    seed: int = 0
    required_level_series: frozenset[str] = frozenset()
    required_event_series: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.rollout_count < 0:
            raise ValueError("rollout_count must be non-negative")
        if self.horizon_months < 0:
            raise ValueError("horizon_months must be non-negative")


@dataclass(frozen=True)
class SampledMarketBundle:
    """Polars-native joint sample of market levels and market events.

    `levels` carries valued series such as asset prices, CPI index levels,
    rent levels, and home-value levels. `events` carries boolean exogenous
    event paths such as private-equity sale windows.
    """

    levels: pl.DataFrame
    events: pl.DataFrame = field(default_factory=lambda: MARKET_EVENTS_SCHEMA.to_frame())
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_schema(self.levels, MARKET_LEVELS_SCHEMA, frame_name="levels")
        _require_schema(self.events, MARKET_EVENTS_SCHEMA, frame_name="events")

    def level_matrix(self, series_id: str, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        """Return one level series as a `(rollout, month)` matrix."""

        return _matrix_from_long_frame(
            self.levels,
            id_column="series_id",
            id_value=series_id,
            value_column="value",
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            dtype=np.float64,
        )

    def event_matrix(self, event_id: str, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        """Return one boolean event series as a `(rollout, month)` matrix."""

        return _matrix_from_long_frame(
            self.events,
            id_column="event_id",
            id_value=event_id,
            value_column="active",
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            dtype=np.bool_,
        )


class ScalarMarketModel(Protocol):
    """One market's marginal model, used inside independent compositions."""

    def sample_levels(self, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        """Return levels shaped `(rollout_count, horizon_months + 1)`."""
        ...


class JointMarketModel(Protocol):
    """Joint market model API consumed by the simulator."""

    def sample(self, request: MarketSamplingRequest) -> SampledMarketBundle:
        """Return all modeled markets as a sampled levels/events bundle."""
        ...


def market_levels_frame(series_id: str, levels: np.ndarray, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    if levels.shape != expected_shape:
        raise ValueError(f"market {series_id!r} produced levels with shape {levels.shape}; expected {expected_shape}")

    rollout_idx, month_idx = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    return pl.DataFrame(
        {
            "rollout_index": rollout_idx,
            "month_index": month_idx,
            "series_id": [series_id] * (rollout_count * (horizon_months + 1)),
            "value": levels.reshape(-1),
        },
        schema=MARKET_LEVELS_SCHEMA,
    )


def market_events_frame(event_id: str, active: np.ndarray, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    if active.shape != expected_shape:
        raise ValueError(
            f"market event {event_id!r} produced mask with shape {active.shape}; expected {expected_shape}"
        )

    rollout_idx, month_idx = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    return pl.DataFrame(
        {
            "rollout_index": rollout_idx,
            "month_index": month_idx,
            "event_id": [event_id] * (rollout_count * (horizon_months + 1)),
            "active": active.reshape(-1),
        },
        schema=MARKET_EVENTS_SCHEMA,
    )


def market_prices_from_levels(bundle: SampledMarketBundle) -> pl.DataFrame:
    """Compatibility projection for the current `augur/sim` price frame."""

    return bundle.levels.rename({"series_id": "asset_id", "value": "price_per_unit_usd"}).select(
        MARKET_PRICES_SCHEMA.names()
    )


def _long_indices(*, rollout_count: int, horizon_months: int) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.repeat(np.arange(rollout_count, dtype=np.int64), horizon_months + 1),
        np.tile(np.arange(horizon_months + 1, dtype=np.int64), rollout_count),
    )


def _require_schema(frame: pl.DataFrame, expected: pl.Schema, *, frame_name: str) -> None:
    if frame.schema != expected:
        raise ValueError(f"{frame_name} schema must be {expected}, got {frame.schema}")


def _matrix_from_long_frame(
    frame: pl.DataFrame,
    *,
    id_column: str,
    id_value: str,
    value_column: str,
    rollout_count: int,
    horizon_months: int,
    dtype: type[np.generic],
) -> np.ndarray:
    selected = frame.filter(pl.col(id_column) == id_value).sort(["rollout_index", "month_index"])
    if selected.is_empty():
        raise KeyError(f"missing sampled market series {id_value!r}")

    expected_rows = rollout_count * (horizon_months + 1)
    if selected.height != expected_rows:
        raise ValueError(f"sampled market series {id_value!r} has {selected.height} rows; expected {expected_rows}")

    expected_rollouts, expected_months = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    actual_rollouts = selected.get_column("rollout_index").to_numpy()
    actual_months = selected.get_column("month_index").to_numpy()
    if not np.array_equal(actual_rollouts, expected_rollouts) or not np.array_equal(actual_months, expected_months):
        raise ValueError(f"sampled market series {id_value!r} does not cover every rollout/month exactly once")

    return selected.get_column(value_column).to_numpy().astype(dtype).reshape((rollout_count, horizon_months + 1))
