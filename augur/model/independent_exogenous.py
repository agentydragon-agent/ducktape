"""Independent-per-series exogenous provider configured from YAML.

The provider lists every external series the simulator may request, mapped to
a scalar level model (Constant / Deterministic / GBM) or event model
(PoissonEvents). Series ids are matched exactly — no prefix templates — so
locations, PE issuers, and crypto symbols are enumerated explicitly. The
model is the only source of price for any series it covers (including the
per-issuer current PE price), exposed both as the month-0 level and as the
`private_equity_prices_usd` metadata dict on the sampled bundle.
"""

from __future__ import annotations

from typing import Literal, assert_never

import jax.numpy as jnp
import numpy as np
from numpyro import distributions as dist
from pydantic import Field

from augur.model.deterministic import Constant, Deterministic
from augur.model.exogenous import ExogenousSamplingRequest, SampledExogenousBundle
from augur.model.gbm import GeometricBrownian
from augur.model.path_models.scenarios import HistoricalSeries
from augur.model.schemas import FrozenModel
from augur.model.series import issuer_id_from_private_equity_mark_wire_id
from augur.model.series_model import IndependentSeriesModels, ScalarSeriesSpec


class IndependentExogenousProviderConfig(FrozenModel):
    """YAML provider that enumerates every series and event explicitly.

    Each `series` entry maps a series id to a scalar level spec. Each
    `events` entry maps an event id to a scalar event spec. Series and event
    ids must match exactly — there is no prefix dispatch.
    """

    type: Literal["independent"] = "independent"
    series: dict[str, ScalarSeriesSpec] = Field(default_factory=dict)

    def realize_model(self) -> IndependentExogenousModel:
        return IndependentExogenousModel(series=self.series)


class IndependentExogenousModel(FrozenModel):
    """Runtime exogenous model built from an `IndependentExogenousProviderConfig`.

    Implements `Sampler` (the runtime sampling contract) and `Scorable` (the
    metric battery contract). No `Fittable` — params are YAML-set, not fit.
    """

    label: str = "independent_exogenous_model"
    series: dict[str, ScalarSeriesSpec]

    @property
    def factor_names(self) -> tuple[str, ...]:
        return tuple(self.series.keys())

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        bundle = IndependentSeriesModels(series=self.series).sample(request)
        return SampledExogenousBundle(
            levels=bundle.levels,
            metadata={"exogenous_model_id": self.label, "private_equity_prices_usd": self._private_equity_prices_usd()},
        )

    def predictive(self, historical: HistoricalSeries, t: int, *, horizon: int = 1) -> dist.Distribution | None:
        """Joint predictive over the cumulative `horizon`-step log-return at
        origin t for the factor list `historical.factor_names`.

        Under per-series independence (the whole point of this provider) the
        joint is a `MultivariateNormal` with diagonal covariance. The
        marginal for factor i is `N(horizon · μ_i, horizon · σ_i²)` — h
        independent N(μ, σ²) increments cumulate to N(hμ, hσ²).

        Returns `None` if any factor in `historical.factor_names` isn't
        backed by a GBM scalar in the provider config — Constant /
        Deterministic factors have zero predictive variance and the
        density is degenerate.
        """
        if horizon < 1:
            raise ValueError(f"horizon must be >= 1; got {horizon}")
        n_steps = historical.levels.shape[0] - 1
        if t + horizon > n_steps:
            return None

        mus: list[float] = []
        sigmas: list[float] = []
        for factor in historical.factor_names:
            spec = self.series.get(factor)
            if not isinstance(spec, GeometricBrownian):
                return None
            mus.append(float(spec.monthly_log_return_mu) * horizon)
            sigmas.append(float(spec.monthly_log_return_sigma) * np.sqrt(horizon))
        mean_arr = jnp.asarray(np.asarray(mus, dtype=np.float32))
        sd_arr = jnp.asarray(np.asarray(sigmas, dtype=np.float32))
        cov_arr = jnp.diag(sd_arr**2)
        return dist.MultivariateNormal(mean_arr, covariance_matrix=cov_arr)

    def _private_equity_prices_usd(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        for series_id, spec in self.series.items():
            issuer_id = issuer_id_from_private_equity_mark_wire_id(series_id)
            if issuer_id is None:
                continue
            prices[issuer_id] = _month_zero_level(spec)
        return prices


def _month_zero_level(spec: ScalarSeriesSpec) -> float:
    if isinstance(spec, Constant):
        return float(spec.value)
    if isinstance(spec, Deterministic):
        return float(spec.levels[0])
    if isinstance(spec, GeometricBrownian):
        return float(spec.initial_value)
    assert_never(spec)
