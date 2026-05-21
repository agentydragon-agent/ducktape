"""Independent external-series model specs that feed `augur/sim`.

The simulator consumes one sampled bundle containing every modeled external
driver. Simple marginal models such as deterministic levels and GBM are
components; the model API is joint so calibrated providers can sample
correlated trajectories in one call.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

import polars as pl
from pydantic import BaseModel, Field

from augur.frames import concat_frames
from augur.model.deterministic import Constant, Deterministic
from augur.model.exogenous import (
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    ExogenousPathModel,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_levels_frame,
    series_values_from_bundle,
)
from augur.model.gbm import GeometricBrownian

ScalarSeriesSpec = Annotated[Constant | Deterministic | GeometricBrownian, Field(discriminator="kind")]


class IndependentSeriesModels(BaseModel):
    """Joint model composed from independent per-series scalar models."""

    kind: Literal["independent"] = "independent"
    series: dict[str, ScalarSeriesSpec] = Field(default_factory=dict)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        if not self.series:
            return SampledExogenousBundle(
                levels=SERIES_LEVELS_SCHEMA.to_frame(), events=SERIES_EVENTS_SCHEMA.to_frame()
            )

        blocks = [
            series_levels_frame(
                series_id,
                model.sample_levels(
                    rollout_seeds=derive_stream_rollout_seeds(request.rollout_seeds, stream_id=series_id),
                    horizon_months=request.horizon_months,
                ),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for series_id, model in self.series.items()
        ]
        return SampledExogenousBundle(
            levels=concat_frames(blocks, SERIES_LEVELS_SCHEMA), events=SERIES_EVENTS_SCHEMA.to_frame()
        )


SeriesModelSpec = IndependentSeriesModels


class SeriesModelBundle(BaseModel):
    """A sim-facing bundle of exogenous series trajectories."""

    model: SeriesModelSpec = Field(default_factory=IndependentSeriesModels)

    @classmethod
    def independent(cls, series: dict[str, ScalarSeriesSpec]) -> SeriesModelBundle:
        return cls(model=IndependentSeriesModels(series=series))

    def sample(
        self,
        *,
        horizon_months: int,
        rollout_seeds: tuple[int, ...],
        required_level_series: frozenset[str] = frozenset(),
        required_event_series: frozenset[str] = frozenset(),
    ) -> SampledExogenousBundle:
        model: ExogenousPathModel = self.model
        return model.sample(
            ExogenousSamplingRequest(
                horizon_months=horizon_months,
                rollout_seeds=rollout_seeds,
                required_level_series=required_level_series,
                required_event_series=required_event_series,
            )
        )


def materialize_series_values(
    bundle: SeriesModelBundle, *, rollout_seeds: tuple[int, ...], horizon_months: int
) -> pl.DataFrame:
    """Project the bundle's sampled levels into the sim external-series frame."""

    return series_values_from_bundle(bundle.sample(rollout_seeds=rollout_seeds, horizon_months=horizon_months))


def derive_stream_rollout_seeds(rollout_seeds: tuple[int, ...], *, stream_id: str) -> tuple[int, ...]:
    """Derive stable per-rollout substream seeds from a model stream id."""

    return tuple(
        int.from_bytes(hashlib.blake2b(f"{seed}:{stream_id}".encode(), digest_size=16).digest(), "big")
        for seed in rollout_seeds
    )
