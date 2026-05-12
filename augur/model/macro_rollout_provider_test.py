"""Shape-contract tests for the generic macro rollout provider.

Parametrised across every label in the registry, so every shipped macro
model is shape-checked against the JointRolloutPath contract automatically.
The model-internal correctness tests live next to each model in
`markets/models/*_test.py`.
"""

from __future__ import annotations

import itertools
import unittest
from pathlib import Path

import numpy as np

from augur.model.macro_rollout_provider import MacroRolloutProvider
from augur.model.markets.registry import LABELS


def _config_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "joint_config.example.json"


class MacroRolloutProviderTest(unittest.TestCase):
    """One subclass per registered label keeps the test names distinct."""


def _make_test(label: str) -> type:
    class _Test(unittest.TestCase):
        @classmethod
        def setUpClass(cls) -> None:
            cls.provider = MacroRolloutProvider.for_label(
                label, config_path=_config_path(), current_private_equity_price_usd=687.69
            )

        def test_metadata_populated(self) -> None:
            assert self.provider.label == label
            assert self.provider.horizon_months > 0
            assert isinstance(self.provider.horizon_start, str)
            assert isinstance(self.provider.latest_observations, dict)

        def test_sample_rollouts_shape(self) -> None:
            n_rollouts = 3
            rollouts = self.provider.sample_rollouts(n_rollouts=n_rollouts, seed=42)
            assert len(rollouts) == n_rollouts
            expected_len = self.provider.horizon_months + 1
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
                multipliers = (
                    "home_value_multipliers",
                    "portfolio_multipliers",
                    "rent_multipliers",
                    "expense_inflation_multipliers",
                )
                for key in multipliers:
                    arr = np.asarray(getattr(rollout, key), dtype="float64")
                    assert abs(arr[0] - 1.0) < 10**-10, key
                    assert np.all(arr > 0), key
                assert set(rollout.home_value_factor_multipliers) == {"sf_home", "vallejo_home"}
                assert set(rollout.rent_factor_multipliers) == {"sf_rent", "vallejo_rent"}
                np.testing.assert_allclose(
                    rollout.home_value_factor_multipliers["sf_home"], rollout.home_value_multipliers
                )
                np.testing.assert_allclose(rollout.rent_factor_multipliers["sf_rent"], rollout.rent_multipliers)

        def test_mortgage_path_constant(self) -> None:
            rollout = self.provider.sample_rollouts(n_rollouts=1, seed=1)[0]
            arr = np.asarray(rollout.mortgage30_rate_path, dtype="float64")
            np.testing.assert_allclose(arr, arr[0])
            assert arr[0] > 0.0

        def test_private_equity_path_flat_with_yearly_tenders(self) -> None:
            rollout = self.provider.sample_rollouts(n_rollouts=1, seed=7)[0]
            path = rollout.private_equity_path
            assert path.current_price_usd > 0.0
            prices = np.asarray(path.price_path, dtype="float64")
            assert len(prices) == self.provider.horizon_months + 1
            np.testing.assert_allclose(prices, prices[0])
            tender_months = [event.month_index for event in path.events]
            assert len(tender_months) > 0
            for event in path.events:
                assert event.event_type == "tender"
                assert event.saleable_fraction == 1.0
            for first, second in itertools.pairwise(tender_months):
                assert second - first == 12
            assert tender_months[0] == 12

        def test_seed_determinism(self) -> None:
            a = self.provider.sample_rollouts(n_rollouts=2, seed=11)
            b = self.provider.sample_rollouts(n_rollouts=2, seed=11)
            for ra, rb in zip(a, b, strict=False):
                np.testing.assert_allclose(ra.portfolio_multipliers, rb.portfolio_multipliers)

    _Test.__name__ = f"MacroRolloutProvider_{label}_Test"
    _Test.__qualname__ = _Test.__name__
    return _Test


# Bootstrap fits trivially; every registered model must shape-check.
for _label in LABELS:
    globals()[f"MacroRolloutProvider_{_label}_Test"] = _make_test(_label)


if __name__ == "__main__":
    unittest.main()
