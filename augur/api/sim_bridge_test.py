from __future__ import annotations

import polars as pl
import pytest
import pytest_bazel

from augur.api.portfolio import (
    PortfolioAccountConfig,
    PortfolioConfig,
    PublicSecurityPositionConfig,
    PublicSecurityTaxLotConfig,
)
from augur.api.sim_bridge import (
    UnsupportedSimBridgeScenarioError,
    sample_and_simulate_translation,
    simulate_translation,
    translate_scenario_set,
)
from augur.core.scenario_set import ScenarioSet
from augur.model.sim_market_series import SP500_SERIES_ID
from augur.model.simple_market import SimpleMarketModel


def _scenario_set_body() -> dict:
    return {
        "scenario_set_id": "sim_bridge_fixture",
        "title": "Sim bridge fixture",
        "market_request": {"market_model_id": "simple", "rollout_count": 3, "horizon_months": 3, "seed": 11},
        "scenarios": [
            {
                "scenario_id": "sp500_spend",
                "label": "SP500 spend",
                "actors": [{"actor_id": "owner", "label": "Owner", "role": "primary_owner"}],
                "initial_balance_sheet": {
                    "accounts": [
                        {
                            "account_id": "checking",
                            "account_type": "checking",
                            "owner_actor_id": "owner",
                            "balance_usd": 0.0,
                        }
                    ],
                    "assets": [
                        {
                            "asset_id": "wealthfront_sp500",
                            "asset_type": "generic_sp500_stock",
                            "owner_actor_id": "owner",
                            "value_usd": 1000.0,
                            "cost_basis_usd": 700.0,
                        }
                    ],
                },
                "policies": [
                    {
                        "policy_id": "monthly_spend",
                        "policy_type": "monthly_spend",
                        "actor_id": "owner",
                        "monthly_spend_usd": 100.0,
                    },
                    {
                        "policy_id": "sell_sp500",
                        "policy_type": "checking_floor_sell_public_stock",
                        "actor_id": "owner",
                        "floor_usd": 0.0,
                        "sale_amount_usd": 0.0,
                    },
                ],
            }
        ],
    }


def test_translate_current_api_shape_to_sim_and_run_with_model_sample() -> None:
    scenario_set = ScenarioSet.model_validate(_scenario_set_body())

    (translation,) = translate_scenario_set(scenario_set)

    assert translation.scenario_id == "sp500_spend"
    assert translation.required_level_series == frozenset({SP500_SERIES_ID})
    assert [agent.agent_id for agent in translation.scenario.agents] == ["external", "owner"]
    assert translation.scenario.initial_lots[0].asset_id == SP500_SERIES_ID
    assert translation.scenario.initial_lots[0].quantity == 1000.0
    assert translation.scenario.initial_lots[0].cost_basis_per_unit_usd == 0.7

    result = simulate_translation(
        SimpleMarketModel(current_private_equity_price_usd=1.0), translation, market_request=scenario_set.market_request
    )

    assert result.market_prices.filter(pl.col("asset_id") == SP500_SERIES_ID).height == 12
    assert result.events_log.obligation_settlements.height == 9
    assert result.events_log.lot_dispositions.height > 0
    assert result.rollout_status.get_column("status").to_list() == ["active", "active", "active"]


def test_bridge_rejects_features_that_do_not_have_sim_semantics_yet() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["property_selection"] = {"property_id": "home_a"}
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedSimBridgeScenarioError, match="property_selection"):
        translate_scenario_set(scenario_set)


def test_configured_portfolio_lots_replace_legacy_public_stock_asset() -> None:
    scenario_set = ScenarioSet.model_validate(_scenario_set_body())
    portfolio = PortfolioConfig(
        accounts=(PortfolioAccountConfig(account_id="taxable_brokerage", owner_agent_id="owner"),),
        public_securities=(
            PublicSecurityPositionConfig(
                position_id="sp500_position",
                account_id="taxable_brokerage",
                symbol="SP500",
                security_kind="other",
                value_series_id=SP500_SERIES_ID,
                unit_value_usd=500.0,
                lots=(
                    PublicSecurityTaxLotConfig(
                        lot_id="sp500_2024_05", holding_period_months_at_start=24, quantity=10.0, cost_basis_usd=3_000.0
                    ),
                    PublicSecurityTaxLotConfig(
                        lot_id="sp500_2026_05", holding_period_months_at_start=0, quantity=5.0, cost_basis_usd=2_000.0
                    ),
                ),
            ),
        ),
    )

    (translation,) = translate_scenario_set(scenario_set, configured_lots=portfolio.to_initial_lots())
    sampled, result = sample_and_simulate_translation(
        SimpleMarketModel(current_private_equity_price_usd=1.0),
        translation,
        market_request=scenario_set.market_request,
        level_anchors=portfolio.level_anchors,
    )

    assert [lot.lot_id for lot in translation.scenario.initial_lots] == ["sp500_2024_05", "sp500_2026_05"]
    assert translation.scenario.initial_lots[0].quantity == 10.0
    assert translation.scenario.initial_lots[0].cost_basis_per_unit_usd == 300.0
    assert sampled.level_matrix(SP500_SERIES_ID, rollout_count=3, horizon_months=3)[:, 0].tolist() == [
        500.0,
        500.0,
        500.0,
    ]
    rollout0_lots = (
        result.asset_lots.filter((pl.col("rollout_index") == 0) & (pl.col("month_index") == 0))
        .sort("lot_id")
        .select("lot_id", "remaining_quantity", "cost_basis_per_unit_usd")
        .iter_rows()
    )
    assert list(rollout0_lots) == [("sp500_2024_05", 10.0, 300.0), ("sp500_2026_05", 5.0, 400.0)]


if __name__ == "__main__":
    pytest_bazel.main()
