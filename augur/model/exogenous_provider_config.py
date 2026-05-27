"""Deployment's choice of exogenous model, as a discriminated YAML config
embedded in `Config.exogenous_provider`.

A deployment supplies one of these per-type configs in its `config.yaml`. The
augur server reads `augur_config.exogenous_provider` at startup and calls
`.realize_model()` to build the runtime exogenous model. Each provider
owns its own state — including current per-issuer private-equity prices —
so the simulator never has to be told about prices out of band.

```yaml
exogenous_provider:
  # Composite provider: a macro model owns public liquid/macro series, while a
  # trained private-equity component owns `private_equity:*` prices and tender
  # opportunity events. VECM intentionally does not synthesize PE fallbacks.
  type: composite
  macro:
    type: vecm
    # /opt/augur/... is where //augur/fit/calibrated:trained_vecm_image_layer
    # bakes the blob in the augur OCI image. Leave null to fall back to the
    # runfiles location of the same blob (used by Bazel-driven dev binaries).
    trained_blob: /opt/augur/trained_vecm.npz
    latest_observations: {sp500: 5500.0, ...}
    current_mortgage30_rate_pct: 6.5
    location_series_sources:
      home_value: {san_francisco_ca: home, vallejo_ca: vallejo_home}
      rent: {san_francisco_ca: rent, ...}
  private_equity:
    type: trained_private_equity
    trained_model_path: /etc/augur/openai_private_equity_model.json
```

```yaml
exogenous_provider:
  # Independent-per-series provider. Every series id is enumerated; PE issuer
  # prices live in the YAML as the `initial_value` of their `private_equity:*`
  # series.
  type: independent
  series:
    inflation: {kind: gbm, initial_value: 1.0, monthly_log_return_mu: 0.00237, monthly_log_return_sigma: 0.00433}
    "private_equity:private_equity_x": {kind: gbm, initial_value: 50.0, monthly_log_return_mu: 0.00642, monthly_log_return_sigma: 0.10103}
    ...
  events:
    "private_equity_sale_opportunity:private_equity_x":
      kind: poisson
      monthly_lambda: 0.013888889
      min_horizon_months: 12
```

Each per-type config lives next to the model/provider it instantiates and
exposes its own `.realize_model()` method. This module is just the
discriminated union that ties them together for Pydantic's type dispatcher.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from augur.model.composite_exogenous import CompositeExogenousModel
from augur.model.independent_exogenous import IndependentExogenousProviderConfig
from augur.model.schemas import FrozenModel
from augur.model.trained_private_equity import TrainedPrivateEquityProviderConfig
from augur.model.vecm import VecmExogenousProviderConfig

BasicExogenousProviderConfig = Annotated[
    IndependentExogenousProviderConfig | VecmExogenousProviderConfig | TrainedPrivateEquityProviderConfig,
    Field(discriminator="type"),
]


class CompositeExogenousProviderConfig(FrozenModel):
    type: Literal["composite"] = "composite"
    macro: BasicExogenousProviderConfig
    private_equity: BasicExogenousProviderConfig

    def realize_model(self) -> CompositeExogenousModel:
        return CompositeExogenousModel(
            macro=self.macro.realize_model(), private_equity=self.private_equity.realize_model()
        )


ExogenousProviderConfig = Annotated[
    IndependentExogenousProviderConfig
    | VecmExogenousProviderConfig
    | TrainedPrivateEquityProviderConfig
    | CompositeExogenousProviderConfig,
    Field(discriminator="type"),
]
