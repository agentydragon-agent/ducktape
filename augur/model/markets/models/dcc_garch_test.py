"""DCC-GJR-GARCH sanity tests."""

from __future__ import annotations

import unittest

import numpy as np

from augur.model.markets.models.dcc_garch import DccGjrGarch
from augur.model.markets.scenarios import HistoricalSeries


def _toy_historical(n_steps: int = 400, n_factors: int = 2, seed: int = 0) -> HistoricalSeries:
    rng = np.random.default_rng(seed)
    chol = np.linalg.cholesky(np.array([[1.0, 0.4], [0.4, 1.0]]))
    z = rng.standard_normal((n_steps, n_factors)) @ chol.T
    sd = np.array([0.04, 0.025])
    log_returns = z * sd
    cum = np.concatenate([np.zeros((1, n_factors)), np.cumsum(log_returns, axis=0)], axis=0)
    levels = np.exp(cum)
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(factor_names=("sp500", "rent"), levels=levels, months=months)


class DccGjrGarchTest(unittest.TestCase):
    def test_fit_runs_and_predictive_density_is_finite(self) -> None:
        historical = _toy_historical()
        model = DccGjrGarch()
        model.fit(historical)
        assert model.mu.shape == (2,)
        assert model.omega.shape == (2,)
        assert np.all(model.omega > 0.0)
        assert np.all(model.alpha >= 0.0)
        assert np.all(model.beta >= 0.0)
        density = model.log_predictive_density(historical, t=200)
        assert np.isfinite(density)

    def test_simulate_produces_valid_paths(self) -> None:
        historical = _toy_historical(n_steps=200, seed=7)
        model = DccGjrGarch()
        model.fit(historical)
        scenarios = model.simulate(n_paths=4, n_months=24, seed=99)
        assert scenarios.multipliers.shape == (4, 25, 2)
        np.testing.assert_array_equal(scenarios.multipliers[:, 0, :], np.ones((4, 2)))
        assert np.all(np.isfinite(scenarios.multipliers))
        assert np.all(scenarios.multipliers > 0)


if __name__ == "__main__":
    unittest.main()
