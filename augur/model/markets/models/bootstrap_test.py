"""Stationary block bootstrap sanity tests."""

from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.model.markets.models.bootstrap import StationaryBootstrap, StationaryBootstrapConfig
from augur.model.markets.scenarios import HistoricalSeries


def _toy_historical(n_steps: int, n_factors: int, seed: int) -> HistoricalSeries:
    rng = np.random.default_rng(seed)
    log_returns = rng.normal(size=(n_steps, n_factors), scale=0.02)
    levels = np.exp(np.concatenate([np.zeros((1, n_factors)), np.cumsum(log_returns, axis=0)], axis=0))
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(factor_names=tuple(f"f{i}" for i in range(n_factors)), levels=levels, months=months)


class TestStationaryBootstrap:
    def test_simulate_uses_only_historical_log_returns(self) -> None:
        historical = _toy_historical(50, 2, seed=1)
        model = StationaryBootstrap(StationaryBootstrapConfig(expected_block_length=8.0))
        model.fit(historical)

        scenarios = model.simulate(n_paths=4, n_months=120, seed=42)
        assert scenarios.multipliers.shape == (4, 121, 2)
        np.testing.assert_array_equal(scenarios.multipliers[:, 0, :], np.ones((4, 2)))
        assert np.all(np.isfinite(scenarios.multipliers))
        assert np.all(scenarios.multipliers > 0)

        # Every simulated log-return must equal one of the historical rows.
        log_returns_sim = np.diff(np.log(scenarios.multipliers), axis=1)
        history = np.diff(np.log(historical.levels), axis=0)
        for path in log_returns_sim:
            for row in path:
                assert np.any(np.all(np.isclose(row, history), axis=1))

    def test_log_predictive_density_returns_none(self) -> None:
        historical = _toy_historical(20, 1, seed=2)
        model = StationaryBootstrap()
        model.fit(historical)
        assert model.log_predictive_density(historical, 5) is None


if __name__ == "__main__":
    pytest_bazel.main()
