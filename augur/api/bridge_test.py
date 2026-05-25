from __future__ import annotations

import polars as pl
import pytest
import pytest_bazel

from augur.api.bridge import (
    UnsupportedBridgeScenarioError,
    sample_and_simulate_translation,
    simulate_translation,
    translate_scenario_set,
)
from augur.api.portfolio import HoldingPositionConfig, HoldingTaxLotConfig, PortfolioAccountConfig, PortfolioConfig
from augur.api.scenario_set import ScenarioSet
from augur.model.exogenous import Sampler
from augur.model.gbm import GeometricBrownian
from augur.model.independent_exogenous import IndependentExogenousProviderConfig
from augur.model.series import SP500_SERIES_ID, private_equity_series_id


@pytest.fixture
def exogenous_model() -> Sampler:
    return IndependentExogenousProviderConfig(
        series={
            SP500_SERIES_ID: GeometricBrownian(initial_value=1.0),
            "inflation": GeometricBrownian(initial_value=1.0),
            private_equity_series_id("private_equity_x"): GeometricBrownian(initial_value=1.0),
        }
    ).realize_model()


def _scenario_set_body() -> dict:
    return {
        "scenario_set_id": "bridge_fixture",
        "title": "Bridge fixture",
        "sampling_request": {"exogenous_model_id": "simple", "rollout_count": 3, "horizon_months": 3, "seed": 11},
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


def test_translate_current_api_shape_to_runtime_and_run_with_model_sample(exogenous_model: Sampler) -> None:
    scenario_set = ScenarioSet.model_validate(_scenario_set_body())

    (translation,) = translate_scenario_set(scenario_set)

    assert translation.scenario_id == "sp500_spend"
    assert translation.required_level_series == frozenset({SP500_SERIES_ID})
    assert [agent.agent_id for agent in translation.scenario.agents] == ["external", "owner"]
    assert translation.scenario.initial_lots[0].asset_id == SP500_SERIES_ID
    assert translation.scenario.initial_lots[0].quantity == 1000.0
    assert translation.scenario.initial_lots[0].cost_basis_per_unit_usd == 0.7

    result = simulate_translation(exogenous_model, translation, sampling_request=scenario_set.sampling_request)

    assert result.series_values.filter(pl.col("series_id") == SP500_SERIES_ID).height == 12
    assert result.events_log.obligation_settlements.height == 9
    assert result.events_log.lot_dispositions.height > 0
    assert result.rollout_status.get_column("status").to_list() == ["active", "active", "active"]


def test_bridge_rejects_features_that_do_not_have_sim_semantics_yet() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["events"] = [
        {"event_id": "move_home", "event_type": "move_residence", "month_index": 1, "actor_id": "owner"}
    ]
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedBridgeScenarioError, match="move_residence"):
        translate_scenario_set(scenario_set)


def test_bridge_rejects_enabled_policy_types_that_are_not_translated() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["policies"].append(
        {
            "policy_id": "partner_accrual",
            "policy_type": "partner_equity_accrual",
            "actor_id": "owner",
            "base_monthly_payment_usd": 1_000.0,
        }
    )
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedBridgeScenarioError, match="partner-equity accrual policies"):
        translate_scenario_set(scenario_set)


def test_bridge_respects_disabled_policies() -> None:
    body = _scenario_set_body()
    for policy in body["scenarios"][0]["policies"]:
        policy["enabled"] = False
    scenario_set = ScenarioSet.model_validate(body)

    (translation,) = translate_scenario_set(scenario_set)

    assert [agent.agent_id for agent in translation.scenario.agents] == ["owner"]
    assert translation.scenario.recurring_obligations == []
    assert translation.scenario.liquidity_policies == []


def test_bridge_rejects_active_occupancy_and_rental_semantics_that_are_not_translated() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["occupancy_plan"] = {"occupancy_mode": "owner_rents_elsewhere"}
    body["scenarios"][0]["rental_plan"] = {"rental_mode": "rent_whole_property", "monthly_rent_usd": 3_000.0}
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedBridgeScenarioError, match=r"occupancy_plan.*rental_plan"):
        translate_scenario_set(scenario_set)


def test_bridge_allows_dormant_not_rented_knobs() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["rental_plan"] = {
        "rental_mode": "not_rented",
        "vacancy_pct": 8,
        "management_fee_pct": 8,
        "leasing_fee_pct": 1,
    }
    scenario_set = ScenarioSet.model_validate(body)

    (translation,) = translate_scenario_set(scenario_set)

    assert translation.scenario.scheduled_property_purchases == []


def test_bridge_rejects_active_tax_and_property_assumption_knobs_that_are_not_translated() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["property_selection"] = {
        "property_id": "sf_home",
        "location_id": "san_francisco",
        "purchase_price_usd": 500_000.0,
    }
    body["scenarios"][0]["tax_profile"] = {"annual_ordinary_income_usd": 50_000.0}
    body["scenarios"][0]["property_assumptions"] = {"depreciable_basis_pct": 75.0}
    body["scenarios"][0]["transaction_costs"] = {"closing_cost_buy_pct": 2.5, "closing_cost_sell_pct": 5.0}
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(
        UnsupportedBridgeScenarioError,
        match=r"tax_profile.*property_assumptions.*transaction_costs\.closing_cost_sell_pct",
    ):
        translate_scenario_set(scenario_set)


def test_bridge_rejects_tax_fields_that_would_be_ignored_by_sim() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["tax_profile"] = {"filing_status": "married_filing_jointly"}
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedBridgeScenarioError, match="tax_profile"):
        translate_scenario_set(scenario_set)

    body = _scenario_set_body()
    body["scenarios"][0]["tax_regimes"] = ["rental_depreciation"]
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedBridgeScenarioError, match=r"tax_regimes .*rental_depreciation"):
        translate_scenario_set(scenario_set)


def test_bridge_rejects_financing_knobs_that_are_not_translated() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["financing"] = {"credit_score": 776}
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedBridgeScenarioError, match="financing"):
        translate_scenario_set(scenario_set)


def test_bridge_rejects_private_equity_liquidity_regimes_that_are_not_translated() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["initial_balance_sheet"]["assets"].append(
        {
            "asset_id": "private_equity_public",
            "asset_type": "private_equity",
            "owner_actor_id": "owner",
            "units": 1_000.0,
            "liquidity_regime": {"regime_type": "public_market"},
        }
    )
    scenario_set = ScenarioSet.model_validate(body)

    with pytest.raises(UnsupportedBridgeScenarioError, match="private-equity liquidity regimes"):
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

    with pytest.raises(UnsupportedBridgeScenarioError, match="private-equity explicit value marks"):
        translate_scenario_set(scenario_set)


def test_property_selection_translates_to_month_zero_purchase_and_mortgage(exogenous_model: Sampler) -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["property_selection"] = {
        "property_id": "sf_home",
        "location_id": "san_francisco",
        "purchase_price_usd": 500_000.0,
    }
    body["scenarios"][0]["initial_balance_sheet"]["accounts"][0]["balance_usd"] = 200_000.0
    body["scenarios"][0]["financing"] = {"financing_mode": "fixed_30", "down_payment_pct": 20, "mortgage_rate_pct": 6.0}
    body["scenarios"][0]["transaction_costs"] = {"closing_cost_buy_pct": 2.0, "closing_cost_sell_pct": 6.5}
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
    assert [(policy.property_id, policy.annual_tax_rate) for policy in translation.scenario.property_tax_policies] == []

    result = simulate_translation(exogenous_model, translation, sampling_request=scenario_set.sampling_request)

    final_property = result.property_state.filter(pl.col("month_index") == 3).row(0, named=True)
    assert final_property["property_id"] == "sf_home"
    assert final_property["location_id"] == "san_francisco"
    assert final_property["adjusted_basis_usd"] == 510_000.0
    final_liability = result.liabilities.filter(pl.col("month_index") == 3).row(0, named=True)
    assert final_liability["liability_id"] == "sf_home_mortgage"
    assert final_liability["principal_usd"] < 400_000.0


def test_property_tax_and_carrying_costs_translate_to_runtime_obligations() -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["property_selection"] = {
        "property_id": "sf_home",
        "location_id": "san_francisco",
        "purchase_price_usd": 600_000.0,
        "local_regulation": {
            "property_tax_regime": "california_prop13",
            "default_tax_regimes": ["california_prop13", "federal_capital_gains", "california_income_tax"],
            "property_tax_annual_pct": 1.2,
            "special_assessment_annual_usd": 1_200.0,
            "notes": "test",
        },
    }
    body["scenarios"][0]["tax_regimes"] = [
        "california_prop13",
        "california_owner_occupied",
        "california_transfer_tax",
        "federal_mortgage_interest",
        "federal_capital_gains",
        "california_income_tax",
        "primary_residence_exclusion",
    ]
    body["scenarios"][0]["tax_profile"] = {"filing_status": "married_filing_jointly", "prior_year_tax_usd": 4_000.0}
    body["scenarios"][0]["initial_balance_sheet"]["accounts"][0]["balance_usd"] = 300_000.0
    body["scenarios"][0]["financing"] = {"financing_mode": "fixed_30", "down_payment_pct": 25, "mortgage_rate_pct": 6.0}
    body["scenarios"][0]["property_assumptions"] = {"insurance_annual_usd": 2_400.0, "maintenance_pct": 1.5}
    body["scenarios"][0]["events"] = [
        {
            "event_id": "purchase",
            "event_type": "property_purchase",
            "month_index": 0,
            "actor_id": "owner",
            "property_id": "sf_home",
            "amount_usd": 600_000.0,
            "hoa_monthly_usd": 250.0,
        }
    ]
    scenario_set = ScenarioSet.model_validate(body)

    (translation,) = translate_scenario_set(scenario_set)

    assert [(policy.property_id, policy.annual_tax_rate) for policy in translation.scenario.property_tax_policies] == [
        ("sf_home", 0.012)
    ]
    assert [
        (profile.filing_status, profile.jurisdiction_ids, profile.tax_authority_agent_id, profile.prior_year_tax_usd)
        for profile in translation.scenario.tax_profiles
    ] == [("married_filing_jointly", ["federal_us", "california"], "tax_authority", 4_000.0)]
    carrying = {
        obligation.obligation_type: obligation.amount_due_usd
        for obligation in translation.scenario.recurring_obligations
        if obligation.obligation_type != "monthly_spend"
    }
    assert carrying == {
        "hoa_dues": 250.0,
        "insurance_premium": 200.0,
        "maintenance": 750.0,
        "special_assessment": 100.0,
    }


def test_configured_portfolio_lots_replace_legacy_public_stock_asset_but_keep_private_equity(
    exogenous_model: Sampler,
) -> None:
    body = _scenario_set_body()
    body["scenarios"][0]["initial_balance_sheet"]["assets"].append(
        {
            "asset_id": "private_equity_private",
            "asset_type": "private_equity",
            "owner_actor_id": "owner",
            "units": 1_000.0,
            "cost_basis_usd": 5_000.0,
            "issuer_id": "private_equity_x",
        }
    )
    scenario_set = ScenarioSet.model_validate(body)
    portfolio = PortfolioConfig(
        accounts=(PortfolioAccountConfig(account_id="taxable_brokerage", owner_agent_id="owner"),),
        holdings=(
            HoldingPositionConfig(
                position_id="sp500_position",
                account_id="taxable_brokerage",
                symbol="SP500",
                security_kind="other",
                value_series_id=SP500_SERIES_ID,
                unit_value_usd=500.0,
                lots=(
                    HoldingTaxLotConfig(
                        lot_id="sp500_2024_05", holding_period_months_at_start=24, quantity=10.0, cost_basis_usd=3_000.0
                    ),
                    HoldingTaxLotConfig(
                        lot_id="sp500_2026_05", holding_period_months_at_start=0, quantity=5.0, cost_basis_usd=2_000.0
                    ),
                ),
            ),
        ),
    )

    (translation,) = translate_scenario_set(scenario_set, configured_lots=portfolio.to_initial_lots())
    sampled, result = sample_and_simulate_translation(
        exogenous_model,
        translation,
        sampling_request=scenario_set.sampling_request,
        level_anchors=portfolio.level_anchors,
    )

    assert [lot.lot_id for lot in translation.scenario.initial_lots] == [
        "sp500_2024_05",
        "sp500_2026_05",
        "private_equity_private_lot",
    ]
    assert translation.scenario.initial_lots[0].quantity == 10.0
    assert translation.scenario.initial_lots[0].cost_basis_per_unit_usd == 300.0
    assert translation.scenario.initial_lots[2].asset_id == private_equity_series_id("private_equity_x")
    assert translation.scenario.initial_lots[2].quantity == 1_000.0
    assert translation.scenario.initial_lots[2].cost_basis_per_unit_usd == 5.0
    assert translation.required_level_series == frozenset(
        {SP500_SERIES_ID, private_equity_series_id("private_equity_x")}
    )
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
