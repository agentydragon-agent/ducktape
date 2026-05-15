"""Shape-contract tests for the generic macro rollout provider.

Parametrised across every label in the registry, so every shipped macro
model is shape-checked against the MarketBundle contract automatically.
The model-internal correctness tests live next to each model in
`markets/models/*_test.py`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import pytest_bazel

from augur.core.scenario_set import MarketRequest
from augur.model.macro_rollout_provider import MacroRolloutProvider
from augur.model.markets.registry import LABELS


@pytest.fixture(params=LABELS)
def provider(request: pytest.FixtureRequest) -> MacroRolloutProvider:
    config_path = Path(__file__).resolve().parent / "config" / "joint_config.example.json"
    return MacroRolloutProvider.for_label(
        request.param, config_path=config_path, current_private_equity_price_usd=100.0
    )


def test_metadata_populated(provider: MacroRolloutProvider) -> None:
    assert provider.label in LABELS
    assert provider.horizon_months > 0
    assert isinstance(provider.horizon_start, str)
    assert isinstance(provider.latest_observations, dict)


def _request(provider: MacroRolloutProvider, *, rollout_count: int = 3, horizon_months: int = 24) -> MarketRequest:
    return MarketRequest(
        market_model_id=provider.label, rollout_count=rollout_count, horizon_months=horizon_months, random_seed=42
    )


def _sample(provider: MacroRolloutProvider, *, rollout_count: int = 3, horizon_months: int = 24):
    request = _request(provider, rollout_count=rollout_count, horizon_months=horizon_months)
    return provider.sample_market_bundle(
        rollout_count=rollout_count, horizon_months=horizon_months, seed=request.random_seed, market_request=request
    )


def test_sample_market_bundle_shape(provider: MacroRolloutProvider) -> None:
    n_rollouts = 3
    horizon_months = 24
    bundle = _sample(provider, rollout_count=n_rollouts, horizon_months=horizon_months)
    expected_shape = (n_rollouts, horizon_months + 1)

    assert bundle.rollout_count == n_rollouts
    assert bundle.horizon_months == horizon_months
    np.testing.assert_array_equal(bundle.month_index, np.arange(horizon_months + 1, dtype="int64"))
    for key in (
        "inflation_multipliers",
        "generic_sp500_multipliers",
        "mortgage_30y_rate_pct",
        "private_equity_value_multipliers",
    ):
        values = getattr(bundle, key)
        assert values.shape == expected_shape, key
        assert np.all(np.isfinite(values)), key
    for key in ("inflation_multipliers", "generic_sp500_multipliers", "private_equity_value_multipliers"):
        values = getattr(bundle, key)
        np.testing.assert_allclose(values[:, 0], 1.0)
        assert np.all(values > 0), key
    expected_locations = {"default", "san_francisco_ca", "vallejo_ca", "mare_island_vallejo_ca"}
    assert set(bundle.home_value_multipliers_by_location) == expected_locations
    assert set(bundle.rent_multipliers_by_location) == expected_locations
    np.testing.assert_allclose(
        bundle.home_value_multipliers_by_location["san_francisco_ca"],
        bundle.home_value_multipliers_by_location["default"],
    )
    np.testing.assert_allclose(
        bundle.rent_multipliers_by_location["san_francisco_ca"], bundle.rent_multipliers_by_location["default"]
    )


def test_mortgage_path_constant(provider: MacroRolloutProvider) -> None:
    bundle = _sample(provider, rollout_count=1, horizon_months=24)
    arr = bundle.mortgage_30y_rate_pct[0]
    np.testing.assert_allclose(arr, arr[0])
    assert arr[0] > 0.0


def test_private_equity_paths_flat_with_yearly_tenders(provider: MacroRolloutProvider) -> None:
    bundle = _sample(provider, rollout_count=1, horizon_months=24)
    np.testing.assert_allclose(bundle.private_equity_value_multipliers, 1.0)
    assert not bundle.private_equity_liquidity_event_mask[:, 0].any()
    assert bundle.private_equity_liquidity_event_mask[:, 12].all()
    assert bundle.private_equity_liquidity_event_mask[:, 24].all()


def test_seed_determinism(provider: MacroRolloutProvider) -> None:
    request = _request(provider, rollout_count=2, horizon_months=24)
    a = provider.sample_market_bundle(rollout_count=2, horizon_months=24, seed=11, market_request=request)
    b = provider.sample_market_bundle(rollout_count=2, horizon_months=24, seed=11, market_request=request)
    np.testing.assert_allclose(a.generic_sp500_multipliers, b.generic_sp500_multipliers)


if __name__ == "__main__":
    pytest_bazel.main()
