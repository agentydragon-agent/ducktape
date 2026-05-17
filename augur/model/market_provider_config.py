"""Deployment's choice of market-bundle provider, as a discriminated YAML config
embedded in `AugurConfig.market_provider`.

A deployment supplies one of these per-type configs in its `config.yaml`. The
augur server reads `augur_config.market_provider` at startup and calls
`.realize(...)` to build the runtime `MarketBundleProvider`.

```yaml
market_provider:
  # Pre-trained macro provider — load the trained blob at startup, no fitting.
  type: vecm
  trained_blob: /etc/augur/trained_vecm.npz
  latest_observations: {sp500: 5500.0, ...}
  current_mortgage30_rate_pct: 6.5
  location_market_sources:
    home_value: {san_francisco_ca: home, vallejo_ca: vallejo_home}
    rent: {san_francisco_ca: rent, ...}
```

```yaml
market_provider:
  # Simple stochastic placeholder. Optional per-location annual spreads.
  type: simple
  location_params:
    san_francisco_ca: {home_value_annual_adjustment_pct: 0.3, rent_annual_adjustment_pct: 0.4}
```

```yaml
market_provider:
  type: noop
```

Each per-type config lives next to the model/provider it instantiates and
exposes its own `.realize(...)` method. This module is just the discriminated
union that ties them together for Pydantic's type dispatcher.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from augur.core.market_bundle import (
    FlatMarketBundleProvider,
    MarketBundleProvider,
    SimpleLocationModelParams,
    SimpleMarketBundleProvider,
    SimpleMarketModelConfig,
)
from augur.core.schemas import ApiModel
from augur.model.markets.models.vecm import VecmMarketProviderConfig


class NoopMarketProviderConfig(ApiModel):
    """Flat / deterministic provider for fixture-backed app + e2e runs."""

    type: Literal["noop"] = "noop"

    def realize(self, *, current_private_equity_price_usd: float) -> MarketBundleProvider:
        return FlatMarketBundleProvider(current_private_equity_price_usd=current_private_equity_price_usd)


class SimpleMarketProviderConfig(ApiModel):
    """Small stochastic placeholder until a calibrated macro model plugs in.

    `location_params` carries the deployment's per-location annual home /
    rent spread — the model has no opinion otherwise. Keys must be a subset
    of the scenario set's required location ids; entries for non-required
    locations error.
    """

    type: Literal["simple"] = "simple"
    location_params: dict[str, SimpleLocationModelParams] = Field(default_factory=dict)

    def realize(self, *, current_private_equity_price_usd: float) -> MarketBundleProvider:
        return SimpleMarketBundleProvider(
            current_private_equity_price_usd=current_private_equity_price_usd,
            model_config=SimpleMarketModelConfig(location_params=self.location_params),
        )


MarketProviderConfig = Annotated[
    NoopMarketProviderConfig | SimpleMarketProviderConfig | VecmMarketProviderConfig, Field(discriminator="type")
]
