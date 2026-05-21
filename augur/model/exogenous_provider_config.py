"""Deployment's choice of exogenous model, as a discriminated YAML config
embedded in `Config.exogenous_provider`.

A deployment supplies one of these per-type configs in its `config.yaml`. The
augur server reads `augur_config.exogenous_provider` at startup and calls
`.realize_model(...)` to build the runtime exogenous model.

```yaml
exogenous_provider:
  # Pre-trained VECM provider — load the trained blob at startup, no fitting.
  type: vecm
  trained_blob: /etc/augur/trained_vecm.npz
  latest_observations: {sp500: 5500.0, ...}
  current_mortgage30_rate_pct: 6.5
  location_series_sources:
    home_value: {san_francisco_ca: home, vallejo_ca: vallejo_home}
    rent: {san_francisco_ca: rent, ...}
```

```yaml
exogenous_provider:
  # Simple stochastic placeholder. Optional per-location annual spreads.
  type: simple
  location_params:
    san_francisco_ca: {home_value_annual_adjustment_pct: 0.3, rent_annual_adjustment_pct: 0.4}
```

Each per-type config lives next to the model/provider it instantiates and
exposes its own `.realize_model(...)` method. This module is just the
discriminated union that ties them together for Pydantic's type dispatcher.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from augur.model.exogenous import ExogenousPathModel
from augur.model.path_models.models.vecm import VecmExogenousProviderConfig
from augur.model.schemas import FrozenModel
from augur.model.simple_exogenous import SimpleExogenousModel, SimpleExogenousModelConfig, SimpleLocationModelParams


class SimpleExogenousProviderConfig(FrozenModel):
    """Small stochastic placeholder until a calibrated macro model plugs in.

    `location_params` carries the deployment's per-location annual home /
    rent spread — the model has no opinion otherwise. Keys must be a subset
    of the scenario set's required location ids; entries for non-required
    locations error.
    """

    type: Literal["simple"] = "simple"
    location_params: dict[str, SimpleLocationModelParams] = Field(default_factory=dict)

    def realize_model(self, *, current_private_equity_price_usd: float) -> ExogenousPathModel:
        return SimpleExogenousModel(
            current_private_equity_price_usd=current_private_equity_price_usd,
            parameters=SimpleExogenousModelConfig(location_params=self.location_params),
        )


ExogenousProviderConfig = Annotated[
    SimpleExogenousProviderConfig | VecmExogenousProviderConfig, Field(discriminator="type")
]


def realize_exogenous_model(
    config: ExogenousProviderConfig, *, current_private_equity_price_usd: float
) -> ExogenousPathModel:
    return config.realize_model(current_private_equity_price_usd=current_private_equity_price_usd)
