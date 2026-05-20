"""VAR(1) Gaussian sanity tests."""

from __future__ import annotations

import math

import numpy as np
import pytest_bazel
from augur.model.markets.models.var import Var1Gaussian

from augur.model.markets.scenarios import HistoricalSeries, historical_log_returns


def _series_from_log_returns(log_returns: np.ndarray) -> HistoricalSeries:
    n_factors = log_returns.shape[1]
    cum = np.concatenate([np.zeros((1, n_factors)), np.cumsum(log_returns, axis=0)], axis=0)
    levels = np.exp(cum)
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(factor_names=tuple(f"f{i}" for i in range(n_factors)), levels=levels, months=months)


def _generate_var1(
    *, intercept: np.ndarray, coef: np.ndarray, cov_chol: np.ndarray, n_steps: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_factors = intercept.shape[0]
    log_returns = np.empty((n_steps, n_factors), dtype="float64")
    state = np.zeros(n_factors)
    for t in range(n_steps):
        innovation = cov_chol @ rng.standard_normal(n_factors)
        state = intercept + coef @ state + innovation
        log_returns[t] = state
    return log_returns


class TestVar1GaussianFit:
    def test_recovers_known_var1_parameters(self) -> None:
        intercept = np.array([0.005, 0.002])
        coef = np.array([[0.30, 0.10], [-0.05, 0.20]])
        cov = np.array([[0.04**2, 0.5 * 0.04 * 0.025], [0.5 * 0.04 * 0.025, 0.025**2]])
        chol = np.linalg.cholesky(cov)
        log_returns = _generate_var1(intercept=intercept, coef=coef, cov_chol=chol, n_steps=10_000, seed=42)
        historical = _series_from_log_returns(log_returns)

        model = Var1Gaussian()
        model.fit(historical)

        np.testing.assert_allclose(model.intercept, intercept, atol=2e-3)
        np.testing.assert_allclose(model.coef, coef, atol=2e-2)
        np.testing.assert_allclose(np.linalg.inv(model.inv_cov), cov, atol=5e-4)

    def test_predictive_log_density_matches_hand_computed_mvn(self) -> None:
        intercept = np.array([0.001, 0.0005, 0.0003])
        coef = np.eye(3) * 0.2
        cov = np.diag([0.03**2, 0.02**2, 0.01**2])
        chol = np.linalg.cholesky(cov)
        log_returns = _generate_var1(intercept=intercept, coef=coef, cov_chol=chol, n_steps=2_000, seed=7)
        historical = _series_from_log_returns(log_returns)

        model = Var1Gaussian()
        model.fit(historical)

        observed_returns = historical_log_returns(historical)
        for t in (1, 5, 100, 999):
            r_t = observed_returns[t]
            r_prev = observed_returns[t - 1]
            mu = model.intercept + model.coef @ r_prev
            diff = r_t - mu
            quad = float(diff @ model.inv_cov @ diff)
            sign, log_det = np.linalg.slogdet(np.linalg.inv(model.inv_cov))
            assert sign > 0
            expected = -0.5 * (3 * math.log(2 * math.pi) + log_det + quad)
            actual = model.log_predictive_density(historical, t)
            assert abs(actual - expected) < 10**-8

    def test_simulate_returns_positive_finite_multipliers_starting_at_one(self) -> None:
        intercept = np.array([0.005, 0.002])
        coef = np.array([[0.20, 0.05], [0.0, 0.15]])
        cov = np.diag([0.04**2, 0.025**2])
        chol = np.linalg.cholesky(cov)
        log_returns = _generate_var1(intercept=intercept, coef=coef, cov_chol=chol, n_steps=500, seed=11)
        historical = _series_from_log_returns(log_returns)

        model = Var1Gaussian()
        model.fit(historical)

        scenarios = model.simulate(n_paths=64, n_months=120, seed=99)
        assert scenarios.multipliers.shape == (64, 121, 2)
        np.testing.assert_array_equal(scenarios.multipliers[:, 0, :], np.ones((64, 2)))
        assert np.all(np.isfinite(scenarios.multipliers))
        assert np.all(scenarios.multipliers > 0)


if __name__ == "__main__":
    pytest_bazel.main()
