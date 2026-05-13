"""VECM sanity tests."""

from __future__ import annotations

import unittest

import numpy as np

from augur.model.markets.models.vecm import VecmConfig, VecmModel
from augur.model.markets.scenarios import HistoricalSeries


def _series_from_log_levels(log_levels: np.ndarray) -> HistoricalSeries:
    levels = np.exp(log_levels - log_levels[0])
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(factor_names=tuple(f"f{i}" for i in range(levels.shape[1])), levels=levels, months=months)


class VecmModelTest(unittest.TestCase):
    def test_fit_runs_on_simulated_cointegrated_series(self) -> None:
        # Build a 2-factor cointegrated random walk: r2 = r1 + small mean-reverting noise.
        rng = np.random.default_rng(42)
        n_steps = 400
        r1 = np.cumsum(rng.normal(scale=0.02, size=n_steps))
        gap = np.zeros(n_steps)
        for t in range(1, n_steps):
            gap[t] = 0.7 * gap[t - 1] + rng.normal(scale=0.005)
        r2 = r1 + gap
        log_levels = np.column_stack([r1, r2])
        log_levels = np.concatenate([np.zeros((1, 2)), log_levels], axis=0)
        historical = _series_from_log_levels(log_levels)

        model = VecmModel(VecmConfig(k_ar_diff=1, coint_rank=1))
        model.fit(historical)

        density = model.log_predictive_density(historical, 200)
        assert density is not None
        assert np.isfinite(density)

    def test_simulate_returns_finite_positive_starting_at_one(self) -> None:
        rng = np.random.default_rng(7)
        n_steps = 200
        r1 = np.cumsum(rng.normal(scale=0.02, size=n_steps))
        gap = np.zeros(n_steps)
        for t in range(1, n_steps):
            gap[t] = 0.7 * gap[t - 1] + rng.normal(scale=0.005)
        r2 = r1 + gap
        log_levels = np.column_stack([r1, r2])
        log_levels = np.concatenate([np.zeros((1, 2)), log_levels], axis=0)
        historical = _series_from_log_levels(log_levels)

        model = VecmModel(VecmConfig(k_ar_diff=1, coint_rank=1))
        model.fit(historical)
        scenarios = model.simulate(n_paths=4, n_months=24, seed=99)
        assert scenarios.multipliers.shape == (4, 25, 2)
        np.testing.assert_array_equal(scenarios.multipliers[:, 0, :], np.ones((4, 2)))
        assert np.all(np.isfinite(scenarios.multipliers))
        assert np.all(scenarios.multipliers > 0)

    def test_h1_horizon_density_approximately_matches_one_step(self) -> None:
        rng = np.random.default_rng(42)
        n_steps = 400
        r1 = np.cumsum(rng.normal(scale=0.02, size=n_steps))
        gap = np.zeros(n_steps)
        for t in range(1, n_steps):
            gap[t] = 0.7 * gap[t - 1] + rng.normal(scale=0.005)
        r2 = r1 + gap
        log_levels = np.column_stack([r1, r2])
        log_levels = np.concatenate([np.zeros((1, 2)), log_levels], axis=0)
        historical = _series_from_log_levels(log_levels)

        model = VecmModel(VecmConfig(k_ar_diff=1, coint_rank=1))
        model.fit(historical)

        for t in (50, 100, 200):
            one_step = model.log_predictive_density(historical, t)
            assert one_step is not None
            h1 = model.log_predictive_density_at_horizon(historical, t, 1)
            assert h1 is not None
            # MC-Gaussian fit on 5000 samples should be within ~1 nat of closed form.
            assert abs(h1 - one_step) < 1.5, f"t={t}: closed={one_step}, h1={h1}"


if __name__ == "__main__":
    unittest.main()
