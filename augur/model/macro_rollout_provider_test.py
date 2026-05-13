"""Shape-contract tests for the generic macro rollout provider.

Parametrised across every label in the registry, so every shipped macro
model is shape-checked against the JointRolloutPath contract automatically.
The model-internal correctness tests live next to each model in
`markets/models/*_test.py`.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest
import pytest_bazel

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


def test_sample_rollouts_shape(provider: MacroRolloutProvider) -> None:
    n_rollouts = 3
    rollouts = provider.sample_rollouts(n_rollouts=n_rollouts, seed=42)
    assert len(rollouts) == n_rollouts
    expected_len = provider.horizon_months + 1
    for rollout in rollouts:
        for key in (
            "home_value_multipliers",
            "sale_home_value_multipliers",
            "portfolio_multipliers",
            "rent_multipliers",
            "expense_inflation_multipliers",
            "mortgage30_rate_path",
        ):
            values = getattr(rollout, key)
            assert len(values) == expected_len, key
            arr = np.asarray(values, dtype="float64")
            assert np.all(np.isfinite(arr)), key
        for key in (
            "home_value_multipliers",
            "portfolio_multipliers",
            "rent_multipliers",
            "expense_inflation_multipliers",
        ):
            arr = np.asarray(getattr(rollout, key), dtype="float64")
            assert abs(arr[0] - 1.0) < 10**-10, key
            assert np.all(arr > 0), key
        assert set(rollout.home_value_factor_multipliers) == {"sf_home", "vallejo_home"}
        assert set(rollout.rent_factor_multipliers) == {"sf_rent", "vallejo_rent"}
        np.testing.assert_allclose(rollout.home_value_factor_multipliers["sf_home"], rollout.home_value_multipliers)
        np.testing.assert_allclose(rollout.rent_factor_multipliers["sf_rent"], rollout.rent_multipliers)


def test_mortgage_path_constant(provider: MacroRolloutProvider) -> None:
    rollout = provider.sample_rollouts(n_rollouts=1, seed=1)[0]
    arr = np.asarray(rollout.mortgage30_rate_path, dtype="float64")
    np.testing.assert_allclose(arr, arr[0])
    assert arr[0] > 0.0


def test_private_equity_path_flat_with_yearly_tenders(provider: MacroRolloutProvider) -> None:
    rollout = provider.sample_rollouts(n_rollouts=1, seed=7)[0]
    path = rollout.private_equity_path
    assert path.current_price_usd > 0.0
    prices = np.asarray(path.price_path, dtype="float64")
    assert len(prices) == provider.horizon_months + 1
    np.testing.assert_allclose(prices, prices[0])
    tender_months = [event.month_index for event in path.events]
    assert len(tender_months) > 0
    for event in path.events:
        assert event.event_type == "tender"
        assert event.saleable_fraction == 1.0
    for first, second in itertools.pairwise(tender_months):
        assert second - first == 12
    assert tender_months[0] == 12


def test_seed_determinism(provider: MacroRolloutProvider) -> None:
    a = provider.sample_rollouts(n_rollouts=2, seed=11)
    b = provider.sample_rollouts(n_rollouts=2, seed=11)
    for ra, rb in zip(a, b, strict=False):
        np.testing.assert_allclose(ra.portfolio_multipliers, rb.portfolio_multipliers)


if __name__ == "__main__":
    pytest_bazel.main()
