"""VECM sanity tests."""

from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.location_series_sources import LocationSeriesSources
from augur.model.path_models.models.vecm import VecmConfig, VecmExogenousPathModel, VecmModel
from augur.model.path_models.scenarios import HistoricalSeries
from augur.model.series import (
    INFLATION_SERIES_ID,
    SP500_SERIES_ID,
    home_value_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
    rent_series_id,
)


def _series_from_log_levels(log_levels: np.ndarray) -> HistoricalSeries:
    levels = np.exp(log_levels - log_levels[0])
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(factor_names=tuple(f"f{i}" for i in range(levels.shape[1])), levels=levels, months=months)


def _historical_series_from_log_levels(log_levels: np.ndarray) -> HistoricalSeries:
    levels = np.exp(log_levels - log_levels[0])
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(factor_names=("sp500", "home", "rent", "inflation"), levels=levels, months=months)


class TestVecmModel:
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

    def test_joint_exogenous_model_samples_levels_and_events(self) -> None:
        rng = np.random.default_rng(123)
        base = np.cumsum(rng.normal(scale=0.01, size=240))
        log_levels = np.column_stack(
            [
                base + rng.normal(scale=0.02, size=240),
                base * 0.8 + rng.normal(scale=0.01, size=240),
                base * 0.4 + rng.normal(scale=0.005, size=240),
                base * 0.2 + rng.normal(scale=0.003, size=240),
            ]
        )
        log_levels = np.concatenate([np.zeros((1, 4)), log_levels], axis=0)
        model = VecmModel(VecmConfig(k_ar_diff=1, coint_rank=1))
        model.fit(_historical_series_from_log_levels(log_levels))
        joint_model = VecmExogenousPathModel.from_loaded_model(
            model,
            latest_observations={"sp500": 5500.0, "home": 1_000_000.0, "rent": 3000.0, "inflation": 320.0},
            current_private_equity_price_usd=50.0,
            location_series_sources=LocationSeriesSources(
                home_value={"san_francisco_ca": "home"}, rent={"san_francisco_ca": "rent"}
            ),
            evidence_source_id="test",
        )

        sampled = joint_model.sample(
            ExogenousSamplingRequest(
                horizon_months=12,
                rollout_seeds=(7, 8),
                required_level_series=frozenset(
                    {
                        SP500_SERIES_ID,
                        INFLATION_SERIES_ID,
                        home_value_series_id("san_francisco_ca"),
                        rent_series_id("san_francisco_ca"),
                        private_equity_series_id("openai"),
                    }
                ),
                required_event_series=frozenset({private_equity_sale_event_id("openai")}),
            )
        )

        assert sampled.level_matrix(SP500_SERIES_ID, rollout_count=2, horizon_months=12)[:, 0].tolist() == [
            5500.0,
            5500.0,
        ]
        assert sampled.level_matrix(home_value_series_id("san_francisco_ca"), rollout_count=2, horizon_months=12)[
            :, 0
        ].tolist() == [1_000_000.0, 1_000_000.0]
        assert (
            sampled.event_matrix(private_equity_sale_event_id("openai"), rollout_count=2, horizon_months=12).dtype
            == np.bool_
        )
        assert sampled.metadata["scenario_generator_id"] == "vecm_exogenous_path_model"


if __name__ == "__main__":
    pytest_bazel.main()
