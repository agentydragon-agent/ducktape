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

import numpy as np

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
