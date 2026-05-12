"""Registry of macro market models.

A single source of truth for both:

- the backend's ``--provider <label>`` flag (`MacroRolloutProvider.for_label(...)`),
- the metric battery driver (`augur.model.metrics_report`).

Each entry is a `MacroModelSpec` carrying the model class, its config, and a
rolling-origin refit cadence (DCC-GARCH is slow to fit so it gets refit every
12 months instead of every step). The label is taken from the class's `label`
attribute to avoid a silent sync risk. Adding a model means adding one row to
`REGISTRY`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from augur.model.markets.market_model import MarketModel
from augur.model.markets.models.bootstrap import StationaryBootstrap, StationaryBootstrapConfig
from augur.model.markets.models.dcc_garch import DccGjrGarch, DccGjrGarchConfig
from augur.model.markets.models.var import Var1Config, Var1Gaussian
from augur.model.markets.models.vecm import VecmConfig, VecmModel
from augur.model.markets.models.wilkie import WilkieCascade, WilkieConfig


@dataclass(frozen=True)
class MacroModelSpec:
    model_cls: type[MarketModel]
    config: Any
    rolling_origin_refit_every: int = 1

    @property
    def label(self) -> str:
        return self.model_cls.label

    def build(self) -> MarketModel:
        return self.model_cls(self.config)


REGISTRY: tuple[MacroModelSpec, ...] = (
    MacroModelSpec(model_cls=Var1Gaussian, config=Var1Config()),
    MacroModelSpec(model_cls=WilkieCascade, config=WilkieConfig()),
    MacroModelSpec(model_cls=VecmModel, config=VecmConfig(k_ar_diff=1, coint_rank=1)),
    MacroModelSpec(model_cls=DccGjrGarch, config=DccGjrGarchConfig(), rolling_origin_refit_every=12),
    MacroModelSpec(model_cls=StationaryBootstrap, config=StationaryBootstrapConfig()),
)

BY_LABEL: dict[str, MacroModelSpec] = {spec.label: spec for spec in REGISTRY}

LABELS: tuple[str, ...] = tuple(BY_LABEL)
