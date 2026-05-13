"""Generic macro-factor rollout provider.

Wraps any `MarketModel` implementation from `augur.model.markets.models.*`
into a `RolloutProvider` the FastAPI server consumes. Composition (provider
holds a market model) instead of inheritance (model implements provider) so
each macro model class stays focused on the macro process and doesn't need to
know about JointRolloutPath / private equity / mortgage. Backend selects a model via
`MacroRolloutProvider.for_label(...)`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from augur.core.schemas import JointRolloutPath, PrivateEquityEvent, PrivateEquityPath
from augur.model.markets.data import load_evidence
from augur.model.markets.market_model import MarketModel
from augur.model.markets.registry import BY_LABEL
from augur.model.projection_factor_sources import ProjectionFactorSources, build_projection_factor_maps

_TENDER_INTERVAL_MONTHS = 12


class MacroRolloutProvider:
    def __init__(
        self, market_model: MarketModel, config_path: Path, *, current_private_equity_price_usd: float
    ) -> None:
        self.config_path = Path(config_path).resolve()
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.label: str = market_model.label
        self.horizon_start: str = config["horizon_start"]
        horizon_years = int(config.get("horizon_years", 30))
        self.horizon_months: int = horizon_years * 12
        self.random_seed: int = int(config.get("random_seed", 0))

        historical, evidence = load_evidence(self.config_path)
        self.latest_observations: dict[str, Any] = dict(evidence.latest_observations)
        self._current_mortgage30_rate_pct = float(evidence.current_mortgage30_rate_pct)
        self._current_private_equity_price_usd = float(current_private_equity_price_usd)
        self._factor_index = {name: idx for idx, name in enumerate(historical.factor_names)}
        self._factor_names = historical.factor_names
        self._projection_factor_sources = ProjectionFactorSources.from_config(config)

        market_model.fit(historical)
        self._market_model = market_model

    @classmethod
    def for_label(
        cls, label: str, *, config_path: Path, current_private_equity_price_usd: float
    ) -> MacroRolloutProvider:
        return cls(
            BY_LABEL[label].build(), config_path, current_private_equity_price_usd=current_private_equity_price_usd
        )

    def sample_rollouts(self, *, n_rollouts: int, seed: int) -> list[JointRolloutPath]:
        scenarios = self._market_model.simulate(n_paths=n_rollouts, n_months=self.horizon_months, seed=seed)
        sp500_idx = self._factor_index["sp500"]
        home_idx = self._factor_index["home"]
        rent_idx = self._factor_index["rent"]
        inflation_idx = self._factor_index["inflation"]

        flat_price_path = [self._current_private_equity_price_usd] * (self.horizon_months + 1)
        # Synthetic tender events at fixed yearly intervals; saleable_fraction=1.0
        # matches the prior tender-only emission and the documented "pretend you
        # can always sell everything" simplification.
        events = [
            PrivateEquityEvent(
                month_index=month,
                event_type="tender",
                price_usd_per_unit=self._current_private_equity_price_usd,
                saleable_fraction=1.0,
            )
            for month in range(_TENDER_INTERVAL_MONTHS, self.horizon_months + 1, _TENDER_INTERVAL_MONTHS)
        ]
        mortgage_path = [self._current_mortgage30_rate_pct] * (self.horizon_months + 1)

        rollouts: list[JointRolloutPath] = []
        for path_idx in range(n_rollouts):
            path = scenarios.multipliers[path_idx]
            path_by_factor = {
                factor_name: [float(v) for v in path[:, factor_index]]
                for factor_name, factor_index in self._factor_index.items()
            }
            home_value_factor_multipliers, rent_factor_multipliers = build_projection_factor_maps(
                path_by_factor=path_by_factor, sources=self._projection_factor_sources
            )
            rollouts.append(
                JointRolloutPath(
                    home_value_multipliers=path_by_factor[self._factor_names[home_idx]],
                    sale_home_value_multipliers=path_by_factor[self._factor_names[home_idx]],
                    portfolio_multipliers=path_by_factor[self._factor_names[sp500_idx]],
                    rent_multipliers=path_by_factor[self._factor_names[rent_idx]],
                    expense_inflation_multipliers=path_by_factor[self._factor_names[inflation_idx]],
                    home_value_factor_multipliers=home_value_factor_multipliers,
                    rent_factor_multipliers=rent_factor_multipliers,
                    mortgage30_rate_path=mortgage_path,
                    private_equity_path=PrivateEquityPath(
                        current_price_usd=self._current_private_equity_price_usd,
                        price_path=flat_price_path,
                        events=events,
                    ),
                )
            )
        return rollouts
