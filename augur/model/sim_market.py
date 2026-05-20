"""Joint market model specs that feed `augur/sim`.

The simulator consumes one sampled bundle containing every modeled
market. Simple marginal models such as deterministic levels and GBM are
components; the public API is joint so calibrated future models can
sample correlated trajectories in one call.
"""

from __future__ import annotations

from typing import Annotated, Literal

import polars as pl
from pydantic import BaseModel, Field

from augur.model.sim_market_api import (
    MARKET_EVENTS_SCHEMA,
    MARKET_LEVELS_SCHEMA,
    JointMarketModel,
    MarketSamplingRequest,
    SampledMarketBundle,
    market_levels_frame,
    market_prices_from_levels,
)
from augur.model.sim_market_deterministic import Constant, Deterministic
from augur.model.sim_market_gbm import GeometricBrownian

ScalarMarketSpec = Annotated[Constant | Deterministic | GeometricBrownian, Field(discriminator="kind")]


class IndependentMarketModels(BaseModel):
    """Joint model composed from independent per-market scalar models."""

    kind: Literal["independent"] = "independent"
    markets: dict[str, ScalarMarketSpec] = Field(default_factory=dict)

    def sample(self, request: MarketSamplingRequest) -> SampledMarketBundle:
        if not self.markets:
            return SampledMarketBundle(levels=MARKET_LEVELS_SCHEMA.to_frame(), events=MARKET_EVENTS_SCHEMA.to_frame())

        blocks = [
            market_levels_frame(
                market_id,
                model.sample_levels(rollout_count=request.rollout_count, horizon_months=request.horizon_months),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for market_id, model in self.markets.items()
        ]
        return SampledMarketBundle(
            levels=pl.concat([MARKET_LEVELS_SCHEMA.to_frame(), *blocks]).select(MARKET_LEVELS_SCHEMA.names()),
            events=MARKET_EVENTS_SCHEMA.to_frame(),
        )


JointMarketSpec = IndependentMarketModels


class MarketBundle(BaseModel):
    """A sim-facing bundle of exogenous market trajectories."""

    model: JointMarketSpec = Field(default_factory=IndependentMarketModels)

    @classmethod
    def independent(cls, markets: dict[str, ScalarMarketSpec]) -> MarketBundle:
        return cls(model=IndependentMarketModels(markets=markets))

    def sample(
        self,
        *,
        rollout_count: int,
        horizon_months: int,
        seed: int = 0,
        required_level_series: frozenset[str] = frozenset(),
        required_event_series: frozenset[str] = frozenset(),
    ) -> SampledMarketBundle:
        model: JointMarketModel = self.model
        return model.sample(
            MarketSamplingRequest(
                rollout_count=rollout_count,
                horizon_months=horizon_months,
                seed=seed,
                required_level_series=required_level_series,
                required_event_series=required_event_series,
            )
        )


def materialize_market_prices(bundle: MarketBundle, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
    """Project the bundle's sampled levels into the current sim price frame."""

    return market_prices_from_levels(bundle.sample(rollout_count=rollout_count, horizon_months=horizon_months))
