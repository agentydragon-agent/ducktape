"""Shared API for exogenous path models consumed by the simulator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral
from typing import Protocol

import numpy as np
import polars as pl

from augur.model.private_equity_bundle import PrivateEquityBundle

SERIES_LEVELS_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)
SERIES_VALUES_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)


@dataclass(frozen=True)
class ExogenousSamplingRequest:
    """Request metadata passed to an exogenous path model sample.

    Non-PE level series are required by wire id in `required_level_series`.
    PE issuers (carrying the whole `PrivateEquityBundle` per issuer) are
    required by `required_private_equity_issuers`. PE tender events and
    protocol channels are part of the bundle, not separate request channels.
    """

    horizon_months: int
    rollout_seeds: tuple[int, ...]
    required_level_series: frozenset[str] = frozenset()
    required_private_equity_issuers: frozenset[str] = frozenset()

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
    """Polars-native joint sample of exogenous levels and PE protocol.

    `levels` carries valued non-PE series (asset prices, CPI levels, rent
    levels, home-value levels). `private_equity` carries the typed PE
    protocol bundle (mark, regime, event kind, sale opportunity, fractions,
    blocked, recovery) per issuer.
    """

    levels: pl.DataFrame
    private_equity: PrivateEquityBundle = field(default_factory=PrivateEquityBundle.empty)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_schema(self.levels, SERIES_LEVELS_SCHEMA, frame_name="levels")

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


class Sampler(Protocol):
    """Runtime sampling boundary — required of every augur exogenous model.

    Anything that can't be sampled is unusable in the augur sim. `Fittable`
    (offline trainer) and `Scorable` (metric battery) extend this protocol
    for models that additionally support training / scoring.
    """

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        """Return all modeled external drivers as a sampled levels bundle."""
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


def series_values_from_bundle(bundle: SampledExogenousBundle) -> pl.DataFrame:
    """Materialize sampled level paths into the sim's external-series frame."""

    return bundle.levels.select(SERIES_VALUES_SCHEMA.names())


def validate_sample_satisfies_request(request: ExogenousSamplingRequest, sampled: SampledExogenousBundle) -> None:
    """Validate that a sampled bundle covers the consumer-requested series ids.

    Providers are free to sample extra series. The request's required ids are a
    consumer compatibility contract, enforced at the boundary that consumes the
    provider.
    """

    missing_level_series = sorted(request.required_level_series - _string_values(sampled.levels, "series_id"))
    sampled_pe_issuers = frozenset(str(issuer) for issuer in sampled.private_equity.issuer_ids())
    missing_pe_issuers = sorted(request.required_private_equity_issuers - sampled_pe_issuers)
    if not missing_level_series and not missing_pe_issuers:
        return

    details: list[str] = []
    if missing_level_series:
        details.append(f"missing required level series: {missing_level_series}")
    if missing_pe_issuers:
        details.append(f"missing required private-equity issuer(s): {missing_pe_issuers}")
    raise ValueError("sampled exogenous bundle " + "; ".join(details))


def anchor_sampled_series_levels(
    sampled: SampledExogenousBundle, level_anchors: Mapping[str, float]
) -> SampledExogenousBundle:
    anchors = {series_id: float(value) for series_id, value in level_anchors.items()}
    if not anchors or sampled.levels.is_empty():
        return sampled

    sampled_series = set(sampled.levels.get_column("series_id").unique().to_list())
    active_anchors = {series_id: value for series_id, value in anchors.items() if series_id in sampled_series}
    private_equity = _anchor_private_equity_marks(sampled.private_equity, anchors=anchors)
    if not active_anchors:
        return SampledExogenousBundle(
            levels=sampled.levels,
            private_equity=private_equity,
            metadata={**sampled.metadata, "level_anchors": anchors},
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
        levels=levels, private_equity=private_equity, metadata={**sampled.metadata, "level_anchors": anchors}
    )


def _anchor_private_equity_marks(pe: PrivateEquityBundle, *, anchors: Mapping[str, float]) -> PrivateEquityBundle:
    """Rescale `mark_usd_per_unit` for each issuer whose `private_equity:<issuer>` wire id
    appears in `anchors`. Mirrors the rescaling applied to the levels frame; the
    portfolio config's `unit_value_usd` is the canonical mark anchor at month 0."""

    if pe.is_empty() or not anchors:
        return pe
    pe_prefix = "private_equity:"
    issuer_anchor: dict[str, float] = {}
    for series_id, anchor_value in anchors.items():
        if series_id.startswith(pe_prefix):
            issuer_anchor[series_id[len(pe_prefix) :]] = anchor_value
    if not issuer_anchor:
        return pe
    frame = pe.frame
    base_frame = frame.filter(pl.col("month_index") == 0).select(
        "rollout_index", "issuer_id", pl.col("mark_usd_per_unit").alias("_base_value")
    )
    anchor_frame = pl.DataFrame(
        {"issuer_id": list(issuer_anchor), "_anchor_value": list(issuer_anchor.values())},
        schema={"issuer_id": pl.Utf8(), "_anchor_value": pl.Float64()},
    )
    joined = (
        frame.join(base_frame, on=["rollout_index", "issuer_id"], how="left")
        .join(anchor_frame, on="issuer_id", how="left")
        .with_columns(
            mark_usd_per_unit=pl.when(pl.col("_anchor_value").is_not_null() & (pl.col("_base_value") > 0.0))
            .then(pl.col("mark_usd_per_unit") * pl.col("_anchor_value") / pl.col("_base_value"))
            .otherwise(pl.col("mark_usd_per_unit"))
        )
        .select(frame.columns)
    )
    return PrivateEquityBundle(frame=joined)


def _long_indices(*, rollout_count: int, horizon_months: int) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.repeat(np.arange(rollout_count, dtype=np.int64), horizon_months + 1),
        np.tile(np.arange(horizon_months + 1, dtype=np.int64), rollout_count),
    )


def _require_schema(frame: pl.DataFrame, expected: pl.Schema, *, frame_name: str) -> None:
    if frame.schema != expected:
        raise ValueError(f"{frame_name} schema must be {expected}, got {frame.schema}")


def _string_values(frame: pl.DataFrame, column: str) -> frozenset[str]:
    if frame.is_empty():
        return frozenset()
    return frozenset(str(value) for value in frame.get_column(column).unique().to_list())


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
