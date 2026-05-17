"""Stationary block bootstrap (Politis & Romano 1994).

Non-parametric: drops a Geometric(p)-length block of historical monthly
log-returns, repeats until the path is the requested length. No
parametric density, so `log_predictive_density` returns None and the
model appears as "unscored" on the comparison table — the metric
machinery accepts that without crashing. Useful as a null baseline
once the rollout-based diagnostics in Phase D land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import Field

from augur.core.market_bundle import MarketBundleProvider
from augur.core.schemas import ApiModel
from augur.model.location_market_sources import LocationMarketSources, LocationMarketSourcesConfig
from augur.model.macro_market_bundle_provider import MacroMarketBundleProvider
from augur.model.markets.scenarios import HistoricalSeries, Scenarios, historical_log_returns


@dataclass(frozen=True)
class StationaryBootstrapConfig:
    """Geometric-block-length parameter for the stationary bootstrap.
    1 / `expected_block_length` is the per-step probability of dropping
    the current block and resampling from a fresh historical index."""

    expected_block_length: float = 12.0

    def __post_init__(self) -> None:
        if self.expected_block_length <= 1.0:
            raise ValueError(f"expected_block_length must be > 1; got {self.expected_block_length}")


def _zeros2() -> np.ndarray:
    return np.zeros((0, 0))


@dataclass
class StationaryBootstrap:
    label = "stationary_bootstrap"

    config: StationaryBootstrapConfig = field(default_factory=StationaryBootstrapConfig)

    historical_log_returns: np.ndarray = field(default_factory=_zeros2)
    factor_names: tuple[str, ...] = ()

    @property
    def _p(self) -> float:
        return 1.0 / self.config.expected_block_length

    def fit(self, historical: HistoricalSeries) -> None:
        self.historical_log_returns = historical_log_returns(historical)
        self.factor_names = historical.factor_names

    def log_predictive_density(self, historical: HistoricalSeries, t: int) -> float | None:
        del historical, t
        return None

    def log_predictive_marginals(self, historical: HistoricalSeries, t: int) -> dict[str, float] | None:
        del historical, t
        return None

    def log_predictive_density_at_horizon(self, historical: HistoricalSeries, t: int, h: int) -> float | None:
        del historical, t, h
        return None

    def save(self, descriptor: StationaryBootstrapMarketProviderConfig) -> None:
        """Persist post-fit state to the `.npz` archive named by the
        descriptor's `trained_blob` so the runtime can skip re-fitting at
        startup. Symmetric to `StationaryBootstrap.load(descriptor)`."""
        np.savez_compressed(
            descriptor.trained_blob,
            expected_block_length=np.array(self.config.expected_block_length),
            historical_log_returns=self.historical_log_returns,
            factor_names=np.array(self.factor_names, dtype=object),
        )

    @staticmethod
    def load(descriptor: StationaryBootstrapMarketProviderConfig) -> StationaryBootstrap:
        with np.load(descriptor.trained_blob, allow_pickle=True) as data:
            config = StationaryBootstrapConfig(expected_block_length=float(data["expected_block_length"]))
            factor_names = tuple(str(name) for name in data["factor_names"])
            model = StationaryBootstrap(config=config)
            model.historical_log_returns = np.asarray(data["historical_log_returns"])
            model.factor_names = factor_names
        return model

    def simulate(self, n_paths: int, n_months: int, seed: int) -> Scenarios:
        rng = np.random.default_rng(seed)
        history = self.historical_log_returns
        n_history, n_factors = history.shape
        log_returns = np.empty((n_paths, n_months, n_factors), dtype="float64")
        for path_index in range(n_paths):
            t = 0
            cursor = int(rng.integers(0, n_history))
            while t < n_months:
                log_returns[path_index, t, :] = history[cursor]
                cursor = (cursor + 1) % n_history
                t += 1
                if rng.random() < self._p:
                    cursor = int(rng.integers(0, n_history))
        cum = np.concatenate([np.zeros((n_paths, 1, n_factors)), np.cumsum(log_returns, axis=1)], axis=1)
        return Scenarios(
            factor_names=self.factor_names or tuple(f"f{i}" for i in range(n_factors)),
            multipliers=np.exp(cum),
            seed=seed,
            label=self.label,
        )


class StationaryBootstrapMarketProviderConfig(ApiModel):
    """Pre-trained stationary bootstrap provider config — points at the
    trained-state blob written by `bb run //augur/model:train`. The model is
    loaded at server startup; no fitting happens on the request path."""

    type: Literal["stationary_bootstrap"] = "stationary_bootstrap"
    trained_blob: Path = Field(
        description="Absolute path to the .npz produced by StationaryBootstrap.save(descriptor)."
    )
    latest_observations: dict[str, Any] = Field(
        description="Latest observed market state at the start of the simulation horizon (factor → value)."
    )
    current_mortgage30_rate_pct: float
    location_market_sources: LocationMarketSourcesConfig

    def realize(self, *, current_private_equity_price_usd: float) -> MarketBundleProvider:
        model = StationaryBootstrap.load(self)
        return MacroMarketBundleProvider.from_loaded_model(
            model,
            latest_observations=self.latest_observations,
            current_mortgage30_rate_pct=self.current_mortgage30_rate_pct,
            current_private_equity_price_usd=current_private_equity_price_usd,
            location_market_sources=LocationMarketSources.from_config(self.location_market_sources),
            evidence_source_id=str(self.trained_blob),
        )
