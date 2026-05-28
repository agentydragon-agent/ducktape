"""Consumer-side external-series context for the simulator.

The simulator consumes materialized per-(series, rollout, month) external
paths. Production evidence ingestion, model fitting, stochastic sampling, and
provenance belong in `augur/model`; `augur/sim` is a deterministic path
evaluator once it receives those trajectories.

The materialized bundle is a long-form polars frame keyed by
`(rollout_index, month_index, series_id)` with one `value` column.
Subsequent step calls index into it by month.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from augur.frames import FrameSpec, concat_frames
from augur.model.exogenous import (
    PRIVATE_EQUITY_PROTOCOL_SCHEMA,
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    SERIES_VALUES_SCHEMA,
    SampledExogenousBundle,
    series_events_frame,
    series_levels_frame,
    series_values_from_bundle,
)
from augur.model.private_equity_bundle import PrivateEquityBundle
from augur.model.series import (
    private_equity_eligible_fraction_series_id,
    private_equity_event_kind_code_series_id,
    private_equity_forced_recovery_cashout_usd_series_id,
    private_equity_forced_sale_fraction_series_id,
    private_equity_liquidity_blocked_series_id,
    private_equity_regime_code_series_id,
    private_equity_sale_capacity_fraction_series_id,
    private_equity_sale_opportunity_wire_id,
    private_equity_series_id,
)
from augur.model.series_model import SeriesModelBundle, materialize_series_values

EXTERNAL_SERIES_VALUES_FRAME = FrameSpec("series_values", SERIES_VALUES_SCHEMA)
EXTERNAL_SERIES_EVENTS_FRAME = FrameSpec("series_events", SERIES_EVENTS_SCHEMA)
PRIVATE_EQUITY_PROTOCOL_FRAME = FrameSpec("private_equity_protocol", PRIVATE_EQUITY_PROTOCOL_SCHEMA)


@dataclass(frozen=True)
class ExternalSeriesContext:
    """The materialized external-series context.

    `series_values` carries non-PE level series (asset prices, CPI levels,
    rent levels). `private_equity` carries the typed PE protocol bundle —
    mark, regime, event-kind, fractions, blocked, recovery — per issuer.

    Legacy `series_events` and `private_equity_protocol` are kept during
    the migration window; new code should use `private_equity` exclusively.
    """

    series_values: pl.DataFrame
    series_events: pl.DataFrame
    private_equity: PrivateEquityBundle = field(default_factory=PrivateEquityBundle.empty)
    private_equity_protocol: pl.DataFrame = field(default_factory=lambda: PRIVATE_EQUITY_PROTOCOL_FRAME.empty())

    def series_at(self, month_index: int) -> pl.DataFrame:
        """Cross-section view at the given month: one row per
        (rollout_index, series_id)."""
        return self.series_values.filter(pl.col("month_index") == month_index).select(
            "rollout_index", "series_id", "value"
        )


def materialize_external_series(
    bundle: SeriesModelBundle, *, rollout_seeds: tuple[int, ...], horizon_months: int
) -> ExternalSeriesContext:
    """Realize every path spec into a long-form polars frame and
    bundle it as a `ExternalSeriesContext`. The output covers months 0
    through `horizon_months` inclusive (so length `horizon_months
    + 1` per (rollout, series)). An empty bundle yields an empty
    frame with the correct schema."""
    return ExternalSeriesContext(
        series_values=EXTERNAL_SERIES_VALUES_FRAME.normalize(
            materialize_series_values(bundle, rollout_seeds=rollout_seeds, horizon_months=horizon_months)
        ),
        series_events=EXTERNAL_SERIES_EVENTS_FRAME.empty(),
        private_equity=PrivateEquityBundle.empty(),
        private_equity_protocol=PRIVATE_EQUITY_PROTOCOL_FRAME.empty(),
    )


def materialize_sampled_exogenous(bundle: SampledExogenousBundle) -> ExternalSeriesContext:
    """Adapt a model-owned sampled bundle into the simulator's series context.

    The typed `PrivateEquityBundle` is the canonical source of PE protocol
    state; the legacy `events` and `private_equity_protocol` frames on the
    sampled bundle are ignored. The sim engine still reads PE channels
    through series-indexed arrays for now, so this expands the bundle back
    into long-form rows on `series_values` (the 8 PE level series),
    `series_events` (tender event), and `private_equity_protocol` (typed
    regime / event-kind codes). Once the engine reads PE channels by issuer
    index, the synthesis goes away. Non-PE series on `bundle.levels` are
    passed through unchanged.
    """

    if bundle.private_equity.is_empty():
        # Test fixtures and other paths that haven't migrated to the typed PE
        # bundle yet still populate the legacy `levels` / `events` /
        # `private_equity_protocol` frames directly. Pass them through.
        return ExternalSeriesContext(
            series_values=EXTERNAL_SERIES_VALUES_FRAME.normalize(series_values_from_bundle(bundle)),
            series_events=EXTERNAL_SERIES_EVENTS_FRAME.normalize(bundle.events),
            private_equity=bundle.private_equity,
            private_equity_protocol=PRIVATE_EQUITY_PROTOCOL_FRAME.normalize(bundle.private_equity_protocol),
        )
    derived_levels, derived_events, derived_protocol = _legacy_frames_from_pe_bundle(bundle.private_equity)
    non_pe_levels = _drop_pe_levels(series_values_from_bundle(bundle))
    return ExternalSeriesContext(
        series_values=EXTERNAL_SERIES_VALUES_FRAME.normalize(
            concat_frames([non_pe_levels, derived_levels], SERIES_VALUES_SCHEMA)
        ),
        series_events=EXTERNAL_SERIES_EVENTS_FRAME.normalize(derived_events),
        private_equity=bundle.private_equity,
        private_equity_protocol=PRIVATE_EQUITY_PROTOCOL_FRAME.normalize(derived_protocol),
    )


def _drop_pe_levels(frame: pl.DataFrame) -> pl.DataFrame:
    """Drop PE-namespaced series ids from a `(series_id, value, …)` frame.

    Materialize_sampled_exogenous synthesizes PE level series from the
    canonical PE bundle; dropping any duplicate PE rows the producer also
    emitted into `levels` is a transitional safeguard until D2's
    double-population is removed in a follow-up commit.
    """

    if frame.is_empty():
        return frame
    return frame.filter(~pl.col("series_id").str.starts_with("private_equity"))


def _legacy_frames_from_pe_bundle(pe: PrivateEquityBundle) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Expand a typed PE bundle into the long-form frames the sim engine still reads.

    The bundle is the canonical source of PE protocol state; this synthesizes:

    - 8 level series per issuer (`private_equity:`, `private_equity_regime_code:`, …)
      that the sim compiler indexes into `external_values`.
    - 1 boolean event series per issuer (`private_equity_sale_opportunity:`).
    - 1 typed protocol frame row per (rollout, month, issuer) with regime and
      event-kind codes.

    Empty bundle → empty frames matching the legacy schemas.
    """

    if pe.is_empty():
        return (
            SERIES_LEVELS_SCHEMA.to_frame(),
            SERIES_EVENTS_SCHEMA.to_frame(),
            PRIVATE_EQUITY_PROTOCOL_SCHEMA.to_frame(),
        )
    frame = pe.frame
    rollout_max = frame.get_column("rollout_index").to_numpy().max(initial=0)
    month_max = frame.get_column("month_index").to_numpy().max(initial=0)
    rollout_count = int(rollout_max) + 1
    horizon_months = int(month_max)
    level_frames: list[pl.DataFrame] = []
    event_frames: list[pl.DataFrame] = []
    protocol_frames: list[pl.DataFrame] = []
    for issuer_id in sorted(pe.issuer_ids()):
        mark = pe.issuer_float_matrix(
            issuer_id, "mark_usd_per_unit", rollout_count=rollout_count, horizon_months=horizon_months
        )
        regime = pe.issuer_int_matrix(
            issuer_id, "regime_code", rollout_count=rollout_count, horizon_months=horizon_months
        ).astype(np.float64)
        event_kind = pe.issuer_int_matrix(
            issuer_id, "event_kind_code", rollout_count=rollout_count, horizon_months=horizon_months
        ).astype(np.float64)
        sale_opp = pe.issuer_bool_matrix(
            issuer_id, "sale_opportunity_active", rollout_count=rollout_count, horizon_months=horizon_months
        )
        sale_capacity = pe.issuer_float_matrix(
            issuer_id, "sale_capacity_fraction", rollout_count=rollout_count, horizon_months=horizon_months
        )
        eligible = pe.issuer_float_matrix(
            issuer_id, "eligible_fraction", rollout_count=rollout_count, horizon_months=horizon_months
        )
        forced_sale = pe.issuer_float_matrix(
            issuer_id, "forced_sale_fraction", rollout_count=rollout_count, horizon_months=horizon_months
        )
        liquidity_blocked = pe.issuer_bool_matrix(
            issuer_id, "liquidity_blocked", rollout_count=rollout_count, horizon_months=horizon_months
        ).astype(np.float64)
        forced_recovery = pe.issuer_float_matrix(
            issuer_id, "forced_recovery_cashout_usd", rollout_count=rollout_count, horizon_months=horizon_months
        )
        for series_id, matrix in (
            (private_equity_series_id(issuer_id), mark),
            (private_equity_regime_code_series_id(issuer_id), regime),
            (private_equity_event_kind_code_series_id(issuer_id), event_kind),
            (private_equity_sale_capacity_fraction_series_id(issuer_id), sale_capacity),
            (private_equity_eligible_fraction_series_id(issuer_id), eligible),
            (private_equity_forced_sale_fraction_series_id(issuer_id), forced_sale),
            (private_equity_liquidity_blocked_series_id(issuer_id), liquidity_blocked),
            (private_equity_forced_recovery_cashout_usd_series_id(issuer_id), forced_recovery),
        ):
            level_frames.append(
                series_levels_frame(series_id, matrix, rollout_count=rollout_count, horizon_months=horizon_months)
            )
        event_frames.append(
            series_events_frame(
                private_equity_sale_opportunity_wire_id(issuer_id),
                sale_opp,
                rollout_count=rollout_count,
                horizon_months=horizon_months,
            )
        )
        protocol_frames.append(
            frame.filter(pl.col("issuer_id") == str(issuer_id)).select(
                ["rollout_index", "month_index", "issuer_id", "regime_code", "event_kind_code"]
            )
        )
    return (
        concat_frames(level_frames, SERIES_LEVELS_SCHEMA),
        concat_frames(event_frames, SERIES_EVENTS_SCHEMA),
        concat_frames(protocol_frames, PRIVATE_EQUITY_PROTOCOL_SCHEMA),
    )
