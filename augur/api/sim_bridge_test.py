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
from augur.model.sim_market_series import SP500_SERIES_ID, private_equity_series_id
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
    body["scenarios"][0]["events"] = [
        {"event_id": "move_home", "event_type": "move_residence", "month_index": 1, "actor_id": "owner"}
    ]
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedSimBridgeScenarioError, match="move_residence"):
        translate_scenario_set(scenario_set)


def test_bridge_rejects_private_equity_explicit_marks_until_series_anchoring_exists() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["initial_balance_sheet"]["assets"].append(
        {
            "asset_id": "private_equity_private",
            "asset_type": "private_equity",
            "owner_actor_id": "owner",
            "units": 1_000.0,
            "value_usd": 100_000.0,
            "cost_basis_usd": 5_000.0,
        }
    )
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedSimBridgeScenarioError, match="private-equity explicit value marks"):
        translate_scenario_set(scenario_set)


def test_property_selection_translates_to_month_zero_purchase_and_mortgage() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["property_selection"] = {
        "property_id": "sf_home",
        "location_id": "san_francisco",
        "purchase_price_usd": 500_000.0,
    }
    body["scenarios"][0]["initial_balance_sheet"]["accounts"][0]["balance_usd"] = 200_000.0
    body["scenarios"][0]["financing"] = {"financing_mode": "fixed_30", "down_payment_pct": 20, "mortgage_rate_pct": 6.0}
    body["scenarios"][0]["transaction_costs"] = {"closing_cost_buy_pct": 2.0, "closing_cost_sell_pct": 0.0}
    body["scenarios"][0]["events"] = [
        {
            "event_id": "purchase",
            "event_type": "property_purchase",
            "month_index": 0,
            "actor_id": "owner",
            "property_id": "sf_home",
            "amount_usd": 500_000.0,
        },
        {
            "event_id": "mortgage",
            "event_type": "mortgage_origination",
            "month_index": 0,
            "actor_id": "owner",
            "property_id": "sf_home",
            "amount_usd": 400_000.0,
        },
    ]
    scenario_set = ScenarioSet.model_validate(body)

    (translation,) = translate_scenario_set(scenario_set)

    assert [agent.agent_id for agent in translation.scenario.agents] == [
        "external",
        "mortgage_lender",
        "owner",
        "property_seller",
    ]
    assert {
        (balance.agent_id, balance.account_id, balance.balance_usd) for balance in translation.scenario.initial_cash
    } >= {("mortgage_lender", "checking", 0.0), ("property_seller", "checking", 0.0)}
    assert len(translation.scenario.scheduled_property_purchases) == 1
    purchase = translation.scenario.scheduled_property_purchases[0]
    assert purchase.month == 0
    assert purchase.property_id == "sf_home"
    assert purchase.location_id == "san_francisco"
    assert purchase.buyer_agent_id == "owner"
    assert purchase.seller_agent_id == "property_seller"
    assert purchase.purchase_price_usd == 500_000.0
    assert purchase.down_payment_usd == 100_000.0
    assert purchase.buyer_closing_cost_usd == 10_000.0
    assert purchase.mortgage is not None
    assert purchase.mortgage.liability_id == "sf_home_mortgage"
    assert purchase.mortgage.lender_agent_id == "mortgage_lender"
    assert purchase.mortgage.principal_usd == 400_000.0
    assert purchase.mortgage.annual_interest_rate == 0.06
    assert purchase.mortgage.term_months == 360

    result = simulate_translation(
        SimpleMarketModel(current_private_equity_price_usd=1.0), translation, market_request=scenario_set.market_request
    )

    final_property = result.property_state.filter(pl.col("month_index") == 3).row(0, named=True)
    assert final_property["property_id"] == "sf_home"
    assert final_property["location_id"] == "san_francisco"
    assert final_property["adjusted_basis_usd"] == 510_000.0
    final_liability = result.liabilities.filter(pl.col("month_index") == 3).row(0, named=True)
    assert final_liability["liability_id"] == "sf_home_mortgage"
    assert final_liability["principal_usd"] < 400_000.0


def test_configured_portfolio_lots_replace_legacy_public_stock_asset_but_keep_private_equity() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["initial_balance_sheet"]["assets"].append(
        {
            "asset_id": "private_equity_private",
            "asset_type": "private_equity",
            "owner_actor_id": "owner",
            "units": 1_000.0,
            "cost_basis_usd": 5_000.0,
            "issuer_id": "openai",
        }
    )
    scenario_set = ScenarioSet.model_validate(body)
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

    assert [lot.lot_id for lot in translation.scenario.initial_lots] == [
        "sp500_2024_05",
        "sp500_2026_05",
        "private_equity_private_lot",
    ]
    assert translation.scenario.initial_lots[0].quantity == 10.0
    assert translation.scenario.initial_lots[0].cost_basis_per_unit_usd == 300.0
    assert translation.scenario.initial_lots[2].asset_id == private_equity_series_id("openai")
    assert translation.scenario.initial_lots[2].quantity == 1_000.0
    assert translation.scenario.initial_lots[2].cost_basis_per_unit_usd == 5.0
    assert translation.required_level_series == frozenset({SP500_SERIES_ID, private_equity_series_id("openai")})
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
    assert list(rollout0_lots) == [
        ("private_equity_private_lot", 1_000.0, 5.0),
        ("sp500_2024_05", 10.0, 300.0),
        ("sp500_2026_05", 5.0, 400.0),
    ]


if __name__ == "__main__":
    pytest_bazel.main()
