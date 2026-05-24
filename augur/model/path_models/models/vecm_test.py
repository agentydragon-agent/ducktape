"""VECM (NumPyro) sanity tests.

These tests exercise the NumPyro-fit VECM end-to-end on synthetic
cointegrated series + the augur runtime sampling boundary. They run on
small horizons / coarse tolerances because SVI/MAP isn't bit-deterministic
across machines.
"""

from __future__ import annotations

import numpy as np
import pytest_bazel
from numpyro import distributions as dist

from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.location_series_sources import LocationSeriesSources
from augur.model.path_models.models.vecm import VecmConfig, VecmModel
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


def _historical_series_4factor(log_levels: np.ndarray) -> HistoricalSeries:
    levels = np.exp(log_levels - log_levels[0])
    months = tuple(f"2000-{i:02d}" for i in range(levels.shape[0]))
    return HistoricalSeries(
        factor_names=("sp500", "home_value:san_francisco_ca", "rent:san_francisco_ca", "inflation"),
        levels=levels,
        months=months,
    )


def _cointegrated_two_factor(seed: int, n_steps: int) -> HistoricalSeries:
    rng = np.random.default_rng(seed)
    r1 = np.cumsum(rng.normal(scale=0.02, size=n_steps))
    gap = np.zeros(n_steps)
    for t in range(1, n_steps):
        gap[t] = 0.7 * gap[t - 1] + rng.normal(scale=0.005)
    r2 = r1 + gap
    log_levels = np.column_stack([r1, r2])
    log_levels = np.concatenate([np.zeros((1, 2)), log_levels], axis=0)
    return _series_from_log_levels(log_levels)


class TestVecmModel:
    def test_fit_then_predictive_returns_a_multivariate_gaussian(self) -> None:
        historical = _cointegrated_two_factor(seed=42, n_steps=200)

        model = VecmModel(config=VecmConfig(n_iters=500))
        model.fit(historical)

        pred = model.predictive(historical, t=100, horizon=1)
        assert isinstance(pred, dist.MultivariateNormal)
        log_levels = np.log(historical.levels)
        observed = log_levels[101] - log_levels[100]
        log_prob = float(np.asarray(pred.log_prob(np.asarray(observed, dtype="float32"))))
        assert np.isfinite(log_prob)

    def test_predictive_returns_none_when_horizon_exceeds_window(self) -> None:
        historical = _cointegrated_two_factor(seed=7, n_steps=150)

        model = VecmModel(config=VecmConfig(n_iters=300))
        model.fit(historical)

        # n_steps observation transitions = 150, so origin t=148 with h=3 has no
        # observed value to score against → predictive returns None.
        assert model.predictive(historical, t=148, horizon=3) is None

    def test_h1_horizon_predictive_matches_one_step_in_distribution(self) -> None:
        historical = _cointegrated_two_factor(seed=42, n_steps=200)

        model = VecmModel(config=VecmConfig(n_iters=500))
        model.fit(historical)

        for t in (50, 100, 150):
            one_step = model.predictive(historical, t, horizon=1)
            h1 = model.predictive(historical, t, horizon=1)
            assert isinstance(one_step, dist.MultivariateNormal)
            assert isinstance(h1, dist.MultivariateNormal)
            # h=1 is closed-form in both paths; same params.
            np.testing.assert_allclose(np.asarray(one_step.mean), np.asarray(h1.mean), atol=1e-6)

    def test_sample_returns_correct_shapes_and_metadata(self) -> None:
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
        historical = _historical_series_4factor(log_levels)

        model = VecmModel(config=VecmConfig(n_iters=500))
        model.fit(historical)
        # Attach deployment-layer state (normally done by realize_model).
        model.latest_observations = {
            "sp500": 5500.0,
            "home_value:san_francisco_ca": 1_000_000.0,
            "rent:san_francisco_ca": 3000.0,
            "inflation": 320.0,
        }
        model.private_equity_prices_usd = {"private_equity_x": 50.0}
        model.location_series_sources = LocationSeriesSources(
            home_value={"san_francisco_ca": "home_value:san_francisco_ca"},
            rent={"san_francisco_ca": "rent:san_francisco_ca"},
        )
        model._compute_provenance(evidence_source_id="test")

        sampled = model.sample(
            ExogenousSamplingRequest(
                horizon_months=12,
                rollout_seeds=(7, 8),
                required_level_series=frozenset(
                    {
                        SP500_SERIES_ID,
                        INFLATION_SERIES_ID,
                        home_value_series_id("san_francisco_ca"),
                        rent_series_id("san_francisco_ca"),
                        private_equity_series_id("private_equity_x"),
                    }
                ),
                required_event_series=frozenset({private_equity_sale_event_id("private_equity_x")}),
            )
        )

        # SP500 paths start at 5500 (the latest observation) and scale by month-0=1 multiplier.
        assert sampled.level_matrix(SP500_SERIES_ID, rollout_count=2, horizon_months=12)[:, 0].tolist() == [
            5500.0,
            5500.0,
        ]
        assert sampled.level_matrix(home_value_series_id("san_francisco_ca"), rollout_count=2, horizon_months=12)[
            :, 0
        ].tolist() == [1_000_000.0, 1_000_000.0]
        assert (
            sampled.event_matrix(
                private_equity_sale_event_id("private_equity_x"), rollout_count=2, horizon_months=12
            ).dtype
            == np.bool_
        )
        assert sampled.metadata["scenario_generator_id"] == "vecm_numpyro"


if __name__ == "__main__":
    pytest_bazel.main()
