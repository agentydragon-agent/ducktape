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

from dataclasses import dataclass

import polars as pl

from augur.frames import FrameSpec
from augur.model.exogenous import SERIES_VALUES_SCHEMA, SampledExogenousBundle, series_values_from_bundle
from augur.model.series_model import SeriesModelBundle, materialize_series_values

EXTERNAL_SERIES_VALUES_FRAME = FrameSpec("series_values", SERIES_VALUES_SCHEMA)


@dataclass(frozen=True)
class ExternalSeriesContext:
    """The materialized external-series frame plus quick filtered views.
    Construct once at sim start; pass alongside `state` into step
    calls. The frame schema is `SERIES_VALUES_SCHEMA`."""

    series_values: pl.DataFrame

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
        )
    )


def materialize_sampled_exogenous(bundle: SampledExogenousBundle) -> ExternalSeriesContext:
    """Adapt a model-owned sampled bundle into the simulator's series context."""

    return ExternalSeriesContext(
        series_values=EXTERNAL_SERIES_VALUES_FRAME.normalize(series_values_from_bundle(bundle))
    )
