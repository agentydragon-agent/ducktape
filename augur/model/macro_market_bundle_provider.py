"""Generic macro market-bundle provider.

Wraps any `MarketModel` implementation from `augur.model.markets.models.*`
as a `MarketBundleProvider` for the scenario-set runtime. Composition keeps
each macro model focused on the macro process; private-equity sale opportunities,
mortgage rates, and location-specific path selection are runtime bundle concerns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from augur.core.market_bundle import MarketBundle, MarketBundleMetadata
from augur.core.scenario_set import MarketRequest
from augur.model.location_market_sources import LocationMarketSources, build_location_market_maps
from augur.model.markets.data import load_evidence
from augur.model.markets.market_model import MarketModel
from augur.model.markets.registry import BY_LABEL

_TENDER_INTERVAL_MONTHS = 12


class MacroMarketBundleProvider:
    def __init__(
        self, market_model: MarketModel, config_path: Path, *, current_private_equity_price_usd: float
    ) -> None:
        self.config_path = Path(config_path).resolve()
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.label: str = market_model.label
        self.horizon_start: str = config["horizon_start"]
        horizon_years = int(config.get("horizon_years", 30))
        self.horizon_months: int = horizon_years * 12
        self.seed: int = int(config.get("seed", 0))

        historical, evidence = load_evidence(self.config_path)
        self.latest_observations: dict[str, Any] = dict(evidence.latest_observations)
        self._current_mortgage30_rate_pct = float(evidence.current_mortgage30_rate_pct)
        self._current_private_equity_price_usd = float(current_private_equity_price_usd)
        self._factor_index = {name: idx for idx, name in enumerate(historical.factor_names)}
        self._location_market_sources = LocationMarketSources.from_config(config)

        market_model.fit(historical)
        self._market_model = market_model

    @classmethod
    def for_label(
        cls, label: str, *, config_path: Path, current_private_equity_price_usd: float
    ) -> MacroMarketBundleProvider:
        return cls(
            BY_LABEL[label].build(), config_path, current_private_equity_price_usd=current_private_equity_price_usd
        )

    def sample_market_bundle(
        self, *, rollout_count: int, horizon_months: int, seed: int, market_request: MarketRequest
    ) -> MarketBundle:
        scenarios = self._market_model.simulate(n_paths=rollout_count, n_months=horizon_months, seed=seed)
        shape = (rollout_count, horizon_months + 1)
        path_by_factor: dict[str, np.ndarray] = {
            factor_name: scenarios.multipliers[:, :, factor_index]
            for factor_name, factor_index in self._factor_index.items()
        }
        home_value_paths_by_location, rent_paths_by_location = build_location_market_maps(
            path_by_factor=path_by_factor, sources=self._location_market_sources
        )
        home_value_paths_by_location = {"default": path_by_factor["home"], **home_value_paths_by_location}
        rent_paths_by_location = {"default": path_by_factor["rent"], **rent_paths_by_location}

        private_equity_events = np.zeros(shape, dtype=np.bool_)
        private_equity_events[:, _TENDER_INTERVAL_MONTHS : horizon_months + 1 : _TENDER_INTERVAL_MONTHS] = True

        return MarketBundle(
            month_index=np.arange(horizon_months + 1, dtype="int64"),
            inflation_multipliers=path_by_factor["inflation"],
            generic_sp500_multipliers=path_by_factor["sp500"],
            home_value_multipliers_by_location=home_value_paths_by_location,
            rent_multipliers_by_location=rent_paths_by_location,
            mortgage_30y_rate_pct=np.full(shape, self._current_mortgage30_rate_pct, dtype="float64"),
            private_equity_value_multipliers=np.ones(shape, dtype="float64"),
            private_equity_sale_opportunity_mask=private_equity_events,
            metadata=MarketBundleMetadata(
                market_model_id=market_request.market_model_id,
                seed=seed,
                rollout_count=rollout_count,
                horizon_months=horizon_months,
                event_stream_ids=("private_equity_sale_opportunity_event",),
                notes=("sampled by MacroMarketBundleProvider",),
                source_metadata={
                    "market_provider_label": self.label,
                    "market_provider_horizon_start": self.horizon_start,
                    "market_provider_horizon_months": self.horizon_months,
                    "market_provider_seed": self.seed,
                    "current_private_equity_price_usd": self._current_private_equity_price_usd,
                    "latest_observation_ids": sorted(str(key) for key in self.latest_observations),
                },
            ),
        )
