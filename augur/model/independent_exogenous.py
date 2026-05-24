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

from pydantic import Field

from augur.model.deterministic import Constant, Deterministic
from augur.model.exogenous import ExogenousPathModel, ExogenousSamplingRequest, SampledExogenousBundle
from augur.model.gbm import GeometricBrownian
from augur.model.schemas import FrozenModel
from augur.model.series import PRIVATE_EQUITY_SERIES_PREFIX, series_suffix
from augur.model.series_model import IndependentSeriesModels, ScalarEventSpec, ScalarSeriesSpec


class IndependentExogenousProviderConfig(FrozenModel):
    """YAML provider that enumerates every series and event explicitly.

    Each `series` entry maps a series id to a scalar level spec. Each
    `events` entry maps an event id to a scalar event spec. Series and event
    ids must match exactly — there is no prefix dispatch.
    """

    type: Literal["independent"] = "independent"
    series: dict[str, ScalarSeriesSpec] = Field(default_factory=dict)
    events: dict[str, ScalarEventSpec] = Field(default_factory=dict)

    def realize_model(self) -> ExogenousPathModel:
        return IndependentExogenousModel(series=self.series, events=self.events)


class IndependentExogenousModel(FrozenModel):
    """Runtime exogenous model built from an `IndependentExogenousProviderConfig`."""

    series: dict[str, ScalarSeriesSpec]
    events: dict[str, ScalarEventSpec]

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        bundle = IndependentSeriesModels(series=self.series, events=self.events).sample(request)
        return SampledExogenousBundle(
            levels=bundle.levels,
            events=bundle.events,
            metadata={
                "exogenous_model_id": "independent_exogenous_model",
                "private_equity_prices_usd": self._private_equity_prices_usd(),
            },
        )

    def _private_equity_prices_usd(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        for series_id, spec in self.series.items():
            issuer_id = series_suffix(series_id, PRIVATE_EQUITY_SERIES_PREFIX)
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
