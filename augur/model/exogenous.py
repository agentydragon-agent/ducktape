"""Shared API for exogenous path models consumed by the simulator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral
from typing import Protocol

import numpy as np
import polars as pl

SERIES_LEVELS_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)
SERIES_EVENTS_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "event_id": pl.Utf8(), "active": pl.Boolean()}
)
SERIES_VALUES_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)


@dataclass(frozen=True)
class ExogenousSamplingRequest:
    """Request metadata passed to an exogenous path model sample."""

    horizon_months: int
    rollout_seeds: tuple[int, ...]
    required_level_series: frozenset[str] = frozenset()
    required_event_series: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.horizon_months < 0:
            raise ValueError("horizon_months must be non-negative")
        seeds = tuple(self.rollout_seeds)
        if not all(isinstance(seed, Integral) for seed in seeds):
            raise TypeError("rollout_seeds must contain integers")
        seeds = tuple(int(seed) for seed in seeds)
        if any(seed < 0 for seed in seeds):
            raise ValueError("rollout_seeds must be non-negative")
        object.__setattr__(self, "rollout_seeds", seeds)

    @property
    def rollout_count(self) -> int:
        """Number of paths requested, derived from the explicit seed vector."""

        return len(self.rollout_seeds)


@dataclass(frozen=True)
class SampledExogenousBundle:
    """Polars-native joint sample of exogenous levels and events.

    `levels` carries valued series such as asset prices, CPI index levels,
    rent levels, and home-value levels. `events` carries boolean exogenous
    event paths such as private-equity sale windows.
    """

    levels: pl.DataFrame
    events: pl.DataFrame = field(default_factory=lambda: SERIES_EVENTS_SCHEMA.to_frame())
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_schema(self.levels, SERIES_LEVELS_SCHEMA, frame_name="levels")
        _require_schema(self.events, SERIES_EVENTS_SCHEMA, frame_name="events")

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


class ExogenousPathModel(Protocol):
    """Joint exogenous path model API consumed by the simulator."""

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        """Return all modeled external drivers as a sampled levels/events bundle."""
        ...


def series_levels_frame(series_id: str, levels: np.ndarray, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    if levels.shape != expected_shape:
        raise ValueError(f"series {series_id!r} produced levels with shape {levels.shape}; expected {expected_shape}")

    rollout_idx, month_idx = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    return pl.DataFrame(
        {
            "rollout_index": rollout_idx,
            "month_index": month_idx,
            "series_id": [series_id] * (rollout_count * (horizon_months + 1)),
            "value": levels.reshape(-1),
        },
        schema=SERIES_LEVELS_SCHEMA,
    )


def series_events_frame(event_id: str, active: np.ndarray, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    if active.shape != expected_shape:
        raise ValueError(
            f"event series {event_id!r} produced mask with shape {active.shape}; expected {expected_shape}"
        )

    rollout_idx, month_idx = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    return pl.DataFrame(
        {
            "rollout_index": rollout_idx,
            "month_index": month_idx,
            "event_id": [event_id] * (rollout_count * (horizon_months + 1)),
            "active": active.reshape(-1),
        },
        schema=SERIES_EVENTS_SCHEMA,
    )


def series_values_from_bundle(bundle: SampledExogenousBundle) -> pl.DataFrame:
    """Materialize sampled level paths into the sim's external-series frame."""

    return bundle.levels.select(SERIES_VALUES_SCHEMA.names())


def anchor_sampled_series_levels(
    sampled: SampledExogenousBundle, level_anchors: Mapping[str, float]
) -> SampledExogenousBundle:
    anchors = {series_id: float(value) for series_id, value in level_anchors.items()}
    if not anchors or sampled.levels.is_empty():
        return sampled

    sampled_series = set(sampled.levels.get_column("series_id").unique().to_list())
    active_anchors = {series_id: value for series_id, value in anchors.items() if series_id in sampled_series}
    if not active_anchors:
        return SampledExogenousBundle(
            levels=sampled.levels, events=sampled.events, metadata={**sampled.metadata, "level_anchors": anchors}
        )

    anchor_frame = pl.DataFrame(
        {"series_id": list(active_anchors), "_anchor_value": list(active_anchors.values())},
        schema={"series_id": pl.Utf8(), "_anchor_value": pl.Float64()},
    )
    bases = (
        sampled.levels.filter(pl.col("month_index") == 0)
        .join(anchor_frame, on="series_id", how="inner")
        .select("rollout_index", "series_id", "_anchor_value", pl.col("value").alias("_base_value"))
    )
    zero_bases = bases.filter(pl.col("_base_value") == 0.0)
    if not zero_bases.is_empty():
        series_ids = sorted(set(zero_bases.get_column("series_id").to_list()))
        raise ValueError(f"sampled series level(s) have zero month-0 value and cannot be anchored: {series_ids}")

    levels = (
        sampled.levels.join(bases, on=["rollout_index", "series_id"], how="left")
        .with_columns(
            value=pl.when(pl.col("_anchor_value").is_not_null())
            .then(pl.col("value") * pl.col("_anchor_value") / pl.col("_base_value"))
            .otherwise(pl.col("value"))
        )
        .select(SERIES_LEVELS_SCHEMA.names())
    )
    return SampledExogenousBundle(
        levels=levels, events=sampled.events, metadata={**sampled.metadata, "level_anchors": anchors}
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
        raise KeyError(f"missing sampled series {id_value!r}")

    expected_rows = rollout_count * (horizon_months + 1)
    if selected.height != expected_rows:
        raise ValueError(f"sampled series {id_value!r} has {selected.height} rows; expected {expected_rows}")

    expected_rollouts, expected_months = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    actual_rollouts = selected.get_column("rollout_index").to_numpy()
    actual_months = selected.get_column("month_index").to_numpy()
    if not np.array_equal(actual_rollouts, expected_rollouts) or not np.array_equal(actual_months, expected_months):
        raise ValueError(f"sampled series {id_value!r} does not cover every rollout/month exactly once")

    return selected.get_column(value_column).to_numpy().astype(dtype).reshape((rollout_count, horizon_months + 1))
