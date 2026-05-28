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

import polars as pl

from augur.frames import FrameSpec
from augur.model.exogenous import (
    PRIVATE_EQUITY_PROTOCOL_SCHEMA,
    SERIES_EVENTS_SCHEMA,
    SERIES_VALUES_SCHEMA,
    SampledExogenousBundle,
    series_values_from_bundle,
)
from augur.model.private_equity_bundle import PrivateEquityBundle
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
    """Adapt a model-owned sampled bundle into the simulator's series context."""

    return ExternalSeriesContext(
        series_values=EXTERNAL_SERIES_VALUES_FRAME.normalize(series_values_from_bundle(bundle)),
        series_events=EXTERNAL_SERIES_EVENTS_FRAME.normalize(bundle.events),
        private_equity=bundle.private_equity,
        private_equity_protocol=PRIVATE_EQUITY_PROTOCOL_FRAME.normalize(bundle.private_equity_protocol),
    )
