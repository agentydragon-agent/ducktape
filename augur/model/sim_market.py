"""Joint market model specs that feed `augur/sim`.

The simulator consumes one materialized frame containing every modeled
market. Simple marginal models such as deterministic prices and GBM are
components; the public API is joint so calibrated future models can
sample correlated trajectories in one call.
"""

from __future__ import annotations

from typing import Annotated, Literal

import polars as pl
from pydantic import BaseModel, Field

from augur.model.sim_market_api import MARKET_PRICES_SCHEMA, JointMarketModel, market_prices_frame
from augur.model.sim_market_deterministic import Constant, Deterministic
from augur.model.sim_market_gbm import GeometricBrownian

ScalarMarketSpec = Annotated[Constant | Deterministic | GeometricBrownian, Field(discriminator="kind")]


class IndependentMarketModels(BaseModel):
    """Joint model composed from independent per-market scalar models."""

    kind: Literal["independent"] = "independent"
    markets: dict[str, ScalarMarketSpec] = Field(default_factory=dict)

    def materialize(self, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
        if not self.markets:
            return MARKET_PRICES_SCHEMA.to_frame()

        blocks = [
            market_prices_frame(
                market_id,
                model.sample_prices(rollout_count=rollout_count, horizon_months=horizon_months),
                rollout_count=rollout_count,
                horizon_months=horizon_months,
            )
            for market_id, model in self.markets.items()
        ]
        return pl.concat([MARKET_PRICES_SCHEMA.to_frame(), *blocks]).select(MARKET_PRICES_SCHEMA.names())


JointMarketSpec = IndependentMarketModels


class MarketBundle(BaseModel):
    """A sim-facing bundle of exogenous market trajectories."""

    model: JointMarketSpec = Field(default_factory=IndependentMarketModels)

    @classmethod
    def independent(cls, markets: dict[str, ScalarMarketSpec]) -> MarketBundle:
        return cls(model=IndependentMarketModels(markets=markets))

    def materialize(self, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
        model: JointMarketModel = self.model
        return model.materialize(rollout_count=rollout_count, horizon_months=horizon_months)


def materialize_market_prices(bundle: MarketBundle, *, rollout_count: int, horizon_months: int) -> pl.DataFrame:
    """Realize the bundle's joint model into a market-price frame."""

    return bundle.materialize(rollout_count=rollout_count, horizon_months=horizon_months)
