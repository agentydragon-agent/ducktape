"""Shared API for exogenous path models consumed by the simulator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral
from typing import Protocol

import numpy as np
import polars as pl

from augur.model.private_equity_bundle import PrivateEquityBundle
from augur.model.series import IssuerId, LevelSeriesKey, parse_level_series_key

SERIES_LEVELS_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)
SERIES_VALUES_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)


@dataclass(frozen=True)
class ExogenousSamplingRequest:
    """Request metadata passed to an exogenous path model sample.

    Non-PE level series are required by typed `LevelSeriesKey` in
    `required_level_series`. PE issuers (carrying the whole
    `PrivateEquityBundle` per issuer) are required by
    `required_private_equity_issuers`. PE tender events and protocol
    channels are part of the PE bundle, not separate request channels.
    """

    horizon_months: int
    rollout_seeds: tuple[int, ...]
    required_level_series: frozenset[LevelSeriesKey] = frozenset()
    required_private_equity_issuers: frozenset[IssuerId] = frozenset()

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
    levels, home-value levels) keyed by the typed `LevelSeriesKey`'s
    `wire_id` in a `series_id: Utf8` column. `private_equity` carries the
    typed PE protocol bundle (mark, regime, event kind, sale opportunity,
    fractions, blocked, recovery) per issuer.
    """

    levels: pl.DataFrame
    private_equity: PrivateEquityBundle = field(default_factory=PrivateEquityBundle.empty)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_schema(self.levels, SERIES_LEVELS_SCHEMA, frame_name="levels")

    def level_matrix(self, key: LevelSeriesKey, *, rollout_count: int, horizon_months: int) -> np.ndarray:
        """Return one level series as a `(rollout, month)` matrix."""

        return _matrix_from_long_frame(
            self.levels,
            id_column="series_id",
            id_value=key.wire_id,
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


def series_levels_frame(
    key: LevelSeriesKey, levels: np.ndarray, *, rollout_count: int, horizon_months: int
) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    if levels.shape != expected_shape:
        raise ValueError(f"series {key.wire_id!r} produced levels with shape {levels.shape}; expected {expected_shape}")

    rollout_idx, month_idx = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    return pl.DataFrame(
        {
            "rollout_index": rollout_idx,
            "month_index": month_idx,
            "series_id": [key.wire_id] * (rollout_count * (horizon_months + 1)),
            "value": levels.reshape(-1),
        },
        schema=SERIES_LEVELS_SCHEMA,
    )


def series_values_from_bundle(bundle: SampledExogenousBundle) -> pl.DataFrame:
    """Materialize sampled level paths into the sim's external-series frame."""

    return bundle.levels.select(SERIES_VALUES_SCHEMA.names())


def validate_sample_satisfies_request(request: ExogenousSamplingRequest, sampled: SampledExogenousBundle) -> None:
    """Validate that a sampled bundle covers the consumer-requested keys.

    Providers are free to sample extra series. The request's required keys
    are a consumer compatibility contract, enforced at the boundary that
    consumes the provider.
    """

    sampled_wire_ids = _string_values(sampled.levels, "series_id")
    missing_level_series = sorted(
        (key for key in request.required_level_series if key.wire_id not in sampled_wire_ids),
        key=lambda key: key.wire_id,
    )
    sampled_pe_issuers = frozenset(IssuerId(str(issuer)) for issuer in sampled.private_equity.issuer_ids())
    missing_pe_issuers = sorted(request.required_private_equity_issuers - sampled_pe_issuers)
    if not missing_level_series and not missing_pe_issuers:
        return

    details: list[str] = []
    if missing_level_series:
        details.append(f"missing required level series: {[key.wire_id for key in missing_level_series]}")
    if missing_pe_issuers:
        details.append(f"missing required private-equity issuer(s): {missing_pe_issuers}")
    raise ValueError("sampled exogenous bundle " + "; ".join(details))


_EMPTY_LEVEL_ANCHORS: Mapping[LevelSeriesKey, float] = {}
_EMPTY_PE_ANCHORS: Mapping[IssuerId, float] = {}


def anchor_sampled_series_levels(
    sampled: SampledExogenousBundle,
    *,
    level_series_anchors: Mapping[LevelSeriesKey, float] = _EMPTY_LEVEL_ANCHORS,
    private_equity_anchors: Mapping[IssuerId, float] = _EMPTY_PE_ANCHORS,
) -> SampledExogenousBundle:
    """Rescale sampled paths so month-0 values match the supplied anchors.

    `level_series_anchors` keys non-PE levels by `LevelSeriesKey`.
    `private_equity_anchors` keys the PE bundle's per-unit mark by
    `IssuerId`. Both anchor maps are typed — the wire-encoded `series_id`
    column on `bundle.levels` is parsed back into typed keys here to align
    with the request channel.
    """

    level_anchors_typed = dict(level_series_anchors)
    pe_anchors_typed = {IssuerId(str(issuer)): float(value) for issuer, value in dict(private_equity_anchors).items()}
    metadata_extras: dict[str, object] = {}
    if level_anchors_typed:
        metadata_extras["level_anchors"] = {key.wire_id: float(value) for key, value in level_anchors_typed.items()}
    if pe_anchors_typed:
        metadata_extras["private_equity_anchors"] = pe_anchors_typed

    private_equity = _anchor_private_equity_marks(sampled.private_equity, pe_anchors_typed)

    if not level_anchors_typed or sampled.levels.is_empty():
        return SampledExogenousBundle(
            levels=sampled.levels, private_equity=private_equity, metadata={**sampled.metadata, **metadata_extras}
        )

    sampled_series = set(sampled.levels.get_column("series_id").unique().to_list())
    active_anchors = {key.wire_id: value for key, value in level_anchors_typed.items() if key.wire_id in sampled_series}
    if not active_anchors:
        return SampledExogenousBundle(
            levels=sampled.levels, private_equity=private_equity, metadata={**sampled.metadata, **metadata_extras}
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
        levels=levels, private_equity=private_equity, metadata={**sampled.metadata, **metadata_extras}
    )


def parse_levels_frame_keys(frame: pl.DataFrame) -> frozenset[LevelSeriesKey]:
    """Recover typed keys for every `series_id` in a levels frame.

    Useful when a producer needs to know the set of distinct keys it
    sampled — the levels frame's `series_id` column is the wire boundary;
    callers above this function should only see `LevelSeriesKey`.
    """

    if frame.is_empty():
        return frozenset()
    return frozenset(parse_level_series_key(str(value)) for value in frame.get_column("series_id").unique().to_list())


def _anchor_private_equity_marks(pe: PrivateEquityBundle, anchors: Mapping[IssuerId, float]) -> PrivateEquityBundle:
    if pe.is_empty() or not anchors:
        return pe
    issuer_anchor = {str(issuer): float(value) for issuer, value in anchors.items()}
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
