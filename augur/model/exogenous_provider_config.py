"""Deployment's choice of exogenous model, as a discriminated YAML config
embedded in `Config.exogenous_provider`.

A deployment supplies one of these per-type configs in its `config.yaml`. The
augur server reads `augur_config.exogenous_provider` at startup and calls
`.realize_model()` to build the runtime exogenous model. Each provider
owns its own state — including current per-issuer private-equity prices —
so the simulator never has to be told about prices out of band.

```yaml
exogenous_provider:
  # Pre-trained VECM provider — load the trained blob at startup, no fitting.
  type: vecm
  trained_blob: /etc/augur/trained_vecm.npz
  latest_observations: {sp500: 5500.0, ...}
  current_mortgage30_rate_pct: 6.5
  private_equity_prices_usd: {private_equity_x: 50.0}
  location_series_sources:
    home_value: {san_francisco_ca: home, vallejo_ca: vallejo_home}
    rent: {san_francisco_ca: rent, ...}
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

from typing import Annotated

from pydantic import Field

from augur.model.independent_exogenous import IndependentExogenousProviderConfig
from augur.model.path_models.models.vecm import VecmExogenousProviderConfig

ExogenousProviderConfig = Annotated[
    IndependentExogenousProviderConfig | VecmExogenousProviderConfig, Field(discriminator="type")
]
