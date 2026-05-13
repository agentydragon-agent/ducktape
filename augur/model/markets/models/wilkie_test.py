"""Wilkie cascade sanity tests."""

from __future__ import annotations

import math
import unittest

import numpy as np

from augur.model.markets.models.wilkie import WilkieCascade
from augur.model.markets.scenarios import HistoricalSeries, historical_log_returns


def _series_from_log_returns(log_returns: np.ndarray, factor_names: tuple[str, ...]) -> HistoricalSeries:
    n_factors = log_returns.shape[1]
    cum = np.concatenate([np.zeros((1, n_factors)), np.cumsum(log_returns, axis=0)], axis=0)
    levels = np.exp(cum)
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(factor_names=factor_names, levels=levels, months=months)


def _generate_cascade(
    *,
    n_steps: int,
    intercept: np.ndarray,
    weight_inflation: np.ndarray,
    weight_own: np.ndarray,
    residual_sd: np.ndarray,
    inflation_index: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_factors = intercept.shape[0]
    log_returns = np.empty((n_steps, n_factors), dtype="float64")
    state = np.zeros(n_factors)
    for t in range(n_steps):
        inflation_lag = state[inflation_index]
        eps = rng.standard_normal(n_factors) * residual_sd
        new = intercept + weight_inflation * inflation_lag + weight_own * state + eps
        log_returns[t] = new
        state = new
    return log_returns


class WilkieCascadeTest(unittest.TestCase):
    def test_recovers_known_cascade_parameters(self) -> None:
        factor_names = ("inflation", "rent", "home", "sp500")
        intercept = np.array([0.002, 0.001, 0.003, 0.005])
        weight_inflation = np.array([0.0, 0.5, 0.3, 0.4])
        weight_own = np.array([0.4, 0.2, 0.6, 0.1])
        residual_sd = np.array([0.003, 0.005, 0.01, 0.04])

        log_returns = _generate_cascade(
            n_steps=10_000,
            intercept=intercept,
            weight_inflation=weight_inflation,
            weight_own=weight_own,
            residual_sd=residual_sd,
            inflation_index=0,
            seed=42,
        )
        historical = _series_from_log_returns(log_returns, factor_names)

        model = WilkieCascade()
        model.fit(historical)

        np.testing.assert_allclose(model.intercept, intercept, atol=2e-3)
        np.testing.assert_allclose(model.weight_inflation, weight_inflation, atol=3e-2)
        np.testing.assert_allclose(model.weight_own, weight_own, atol=3e-2)
        np.testing.assert_allclose(model.residual_sd, residual_sd, atol=2e-3)

    def test_predictive_log_density_matches_independent_gaussians(self) -> None:
        factor_names = ("inflation", "rent")
        intercept = np.array([0.001, 0.0005])
        weight_inflation = np.array([0.0, 0.4])
        weight_own = np.array([0.3, 0.2])
        residual_sd = np.array([0.005, 0.008])

        log_returns = _generate_cascade(
            n_steps=2_000,
            intercept=intercept,
            weight_inflation=weight_inflation,
            weight_own=weight_own,
            residual_sd=residual_sd,
            inflation_index=0,
            seed=11,
        )
        historical = _series_from_log_returns(log_returns, factor_names)

        model = WilkieCascade()
        model.fit(historical)

        observed = historical_log_returns(historical)
        for t in (1, 100, 1999):
            r_t = observed[t]
            r_prev = observed[t - 1]
            mu = model.intercept + model.weight_inflation * r_prev[0] + model.weight_own * r_prev
            diff = r_t - mu
            sd = model.residual_sd
            expected = float(np.sum(-0.5 * ((diff / sd) ** 2) - np.log(sd) - 0.5 * math.log(2 * math.pi)))
            actual = model.log_predictive_density(historical, t)
            assert actual is not None
            assert abs(actual - expected) < 10**-8

    def test_simulate_returns_finite_positive_paths_starting_at_one(self) -> None:
        factor_names = ("inflation", "rent")
        intercept = np.array([0.002, 0.001])
        weight_inflation = np.array([0.0, 0.3])
        weight_own = np.array([0.3, 0.1])
        residual_sd = np.array([0.005, 0.01])
        log_returns = _generate_cascade(
            n_steps=500,
            intercept=intercept,
            weight_inflation=weight_inflation,
            weight_own=weight_own,
            residual_sd=residual_sd,
            inflation_index=0,
            seed=23,
        )
        historical = _series_from_log_returns(log_returns, factor_names)

        model = WilkieCascade()
        model.fit(historical)

        scenarios = model.simulate(n_paths=32, n_months=120, seed=77)
        assert scenarios.multipliers.shape == (32, 121, 2)
        np.testing.assert_array_equal(scenarios.multipliers[:, 0, :], np.ones((32, 2)))
        assert np.all(np.isfinite(scenarios.multipliers))
        assert np.all(scenarios.multipliers > 0)


if __name__ == "__main__":
    unittest.main()
