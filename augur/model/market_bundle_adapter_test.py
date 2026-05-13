from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest_bazel

from augur.core.scenario_engine import run_scenario_set_vectorized
from augur.core.scenario_set import MarketRequest, ScenarioSet
from augur.core.schemas import JointRolloutPath, PrivateEquityEvent, PrivateEquityPath
from augur.model.market_bundle_adapter import RolloutProviderMarketBundleProvider


class _FakeRolloutProvider:
    label = "fake_joint"
    horizon_start = "2026-05-01"
    horizon_months = 12
    random_seed = 2468
    latest_observations: ClassVar[dict[str, dict[str, float]]] = {
        "sp500_latest": {"value": 5000},
        "mortgage30_latest": {"value": 6.75},
    }

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def sample_rollouts(self, *, n_rollouts: int, seed: int) -> list[JointRolloutPath]:
        self.calls.append((n_rollouts, seed))
        month_count = self.horizon_months + 1
        rollouts: list[JointRolloutPath] = []
        for rollout_index in range(n_rollouts):
            months = np.arange(month_count, dtype="float64")
            sf_home = 1.0 + 0.01 * months + rollout_index * 0.001 * months
            vallejo_home = 1.0 + 0.02 * months + rollout_index * 0.002 * months
            sf_rent = 1.0 + 0.003 * months
            vallejo_rent = 1.0 + 0.004 * months
            sp500 = 1.0 + 0.05 * months + rollout_index * 0.01 * months
            inflation = 1.0 + 0.002 * months
            private_equity_price = 10.0 * (1.0 + 0.10 * months + rollout_index * 0.01 * months)
            rollouts.append(
                JointRolloutPath(
                    home_value_multipliers=sf_home.tolist(),
                    sale_home_value_multipliers=sf_home.tolist(),
                    portfolio_multipliers=sp500.tolist(),
                    rent_multipliers=sf_rent.tolist(),
                    expense_inflation_multipliers=inflation.tolist(),
                    home_value_factor_multipliers={"sf_home": sf_home.tolist(), "vallejo_home": vallejo_home.tolist()},
                    rent_factor_multipliers={"sf_rent": sf_rent.tolist(), "vallejo_rent": vallejo_rent.tolist()},
                    mortgage30_rate_path=(6.5 + 0.01 * months).tolist(),
                    private_equity_path=PrivateEquityPath(
                        current_price_usd=10,
                        price_path=private_equity_price.tolist(),
                        events=[
                            PrivateEquityEvent(
                                month_index=2,
                                event_type="tender",
                                price_usd_per_unit=float(private_equity_price[2]),
                                saleable_fraction=0.25 + 0.05 * rollout_index,
                            ),
                            PrivateEquityEvent(
                                month_index=5,
                                event_type="acquisition",
                                price_usd_per_unit=float(private_equity_price[5]),
                            ),
                            PrivateEquityEvent(
                                month_index=99,
                                event_type="tender",
                                price_usd_per_unit=float(private_equity_price[-1]),
                                saleable_fraction=0.9,
                            ),
                        ],
                    ),
                )
            )
        return rollouts


def test_rollout_provider_market_bundle_adapter_maps_shapes_factors_and_metadata() -> None:
    provider = _FakeRolloutProvider()
    adapter = RolloutProviderMarketBundleProvider(provider)
    request = MarketRequest(market_model_id="current_joint_model", rollout_count=2, horizon_months=6, random_seed=99)

    bundle = adapter.sample_market_bundle(
        rollout_count=request.rollout_count,
        horizon_months=request.horizon_months,
        seed=request.random_seed,
        market_request=request,
    )

    assert provider.calls == [(2, 99)]
    assert bundle.generic_sp500_multipliers.shape == (2, 7)
    assert bundle.inflation_multipliers.shape == (2, 7)
    assert bundle.mortgage_30y_rate_pct.shape == (2, 7)
    np.testing.assert_array_equal(bundle.month_index, np.arange(7, dtype="int64"))

    np.testing.assert_allclose(
        bundle.home_value_multipliers_by_location["default"][0], [1, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06]
    )
    np.testing.assert_allclose(
        bundle.home_value_multipliers_by_location["sf_home"],
        bundle.home_value_multipliers_by_location["san_francisco_ca"],
    )
    np.testing.assert_allclose(
        bundle.home_value_multipliers_by_location["vallejo_home"],
        bundle.home_value_multipliers_by_location["vallejo_ca"],
    )
    np.testing.assert_allclose(
        bundle.home_value_multipliers_by_location["vallejo_home"],
        bundle.home_value_multipliers_by_location["mare_island_vallejo_ca"],
    )
    np.testing.assert_allclose(
        bundle.rent_multipliers_by_location["sf_rent"], bundle.rent_multipliers_by_location["san_francisco_ca"]
    )
    np.testing.assert_allclose(
        bundle.rent_multipliers_by_location["vallejo_rent"], bundle.rent_multipliers_by_location["vallejo_ca"]
    )

    np.testing.assert_allclose(bundle.private_equity_value_multipliers[0], [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6])
    assert bundle.private_equity_liquidity_event_mask.dtype == np.bool_
    assert bundle.private_equity_liquidity_event_mask[0, 2]
    assert bundle.private_equity_liquidity_event_mask[1, 2]
    assert bundle.private_equity_liquidity_event_mask[0, 5]
    assert not bundle.private_equity_liquidity_event_mask[0, 6]
    np.testing.assert_allclose(bundle.private_equity_tender_sale_fraction[:, 2], [0.25, 0.30])
    np.testing.assert_allclose(bundle.private_equity_tender_sale_fraction[:, 5], [1.0, 1.0])
    np.testing.assert_allclose(bundle.private_equity_tender_sale_fraction[:, 6], [0.0, 0.0])

    factor_ids = set(bundle.metadata.factor_ids)
    assert "inflation" in factor_ids
    assert "expense_inflation" in factor_ids
    assert "generic_sp500" in factor_ids
    assert "mortgage30_rate" in factor_ids
    assert "private_equity_value" in factor_ids
    assert "home_value:sf_home" in factor_ids
    assert "home_value:vallejo_home" in factor_ids
    assert "rent:sf_rent" in factor_ids
    assert "rent:vallejo_rent" in factor_ids
    assert bundle.metadata.source_metadata["rollout_provider_label"] == "fake_joint"
    assert bundle.metadata.source_metadata["rollout_provider_horizon_start"] == "2026-05-01"
    assert bundle.metadata.source_metadata["latest_observation_ids"] == ["mortgage30_latest", "sp500_latest"]


def test_rollout_provider_market_bundle_adapter_uses_provider_seed_when_request_seed_is_absent() -> None:
    provider = _FakeRolloutProvider()
    adapter = RolloutProviderMarketBundleProvider(provider)

    adapter.sample_market_bundle(
        rollout_count=1, horizon_months=3, seed=None, market_request=MarketRequest(rollout_count=1, horizon_months=3)
    )

    assert provider.calls == [(1, provider.random_seed)]


def test_scenario_set_runner_shares_one_adapter_sample_across_scenarios() -> None:
    provider = _FakeRolloutProvider()
    adapter = RolloutProviderMarketBundleProvider(provider)
    scenario_set = ScenarioSet.model_validate(
        {
            "scenario_set_id": "shared_adapter_sample",
            "title": "Shared adapter sample",
            "market_request": {"rollout_count": 2, "horizon_months": 6, "random_seed": 77},
            "scenarios": [_portfolio_scenario("first", 100_000), _portfolio_scenario("second", 200_000)],
        }
    )

    response = run_scenario_set_vectorized(scenario_set, market_provider=adapter)

    assert provider.calls == [(2, 77)]
    first = response.scenario_results[0].monthly_columns.columns["generic_sp500_value_usd"]
    second = response.scenario_results[1].monthly_columns.columns["generic_sp500_value_usd"]
    np.testing.assert_allclose(np.asarray(second) / np.asarray(first), 2.0)
    assert response.market_metadata["source_metadata"]["rollout_provider_label"] == "fake_joint"


def _portfolio_scenario(scenario_id: str, sp500_usd: float) -> dict:
    return {
        "scenario_id": scenario_id,
        "label": scenario_id.title(),
        "actors": [{"actor_id": "owner", "label": "Owner", "role": "primary_owner"}],
        "initial_balance_sheet": {
            "assets": [
                {
                    "asset_id": "sp500",
                    "asset_type": "generic_sp500_stock",
                    "owner_actor_id": "owner",
                    "value_usd": sp500_usd,
                }
            ]
        },
    }


if __name__ == "__main__":
    pytest_bazel.main()
