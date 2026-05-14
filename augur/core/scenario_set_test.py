from __future__ import annotations

import copy
import re
from typing import Any

import pytest
import pytest_bazel
from pydantic import ValidationError

from augur.core.local_regulation import LocationId
from augur.core.scenario_set import (
    AccountType,
    ActorRole,
    AssetType,
    FinancingMode,
    FixedAmountPrivateEquitySaleRule,
    LiquidityReservePolicy,
    OccupancyMode,
    PolicyType,
    PrivateEquitySalePolicy,
    PrivateEquitySaleProceedsDestination,
    ProjectedDeficitsLiquidityReserveRule,
    RentalMode,
    ScenarioAcceptedSummary,
    ScenarioResult,
    ScenarioResultStatus,
    ScenarioSet,
    TaxRegime,
)

_SNAKE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


def _scenario_set_body(*scenario_ids: str) -> dict[str, Any]:
    return {
        "scenario_set_id": "compare_sf_and_vallejo",
        "title": "Compare SF and Vallejo",
        "market_request": {
            "market_model_id": "current_joint_model",
            "rollout_count": 32,
            "horizon_months": 120,
            "random_seed": 7,
            "shared_market_paths": True,
        },
        "report_spec": {
            "metrics": ["net_worth", "liquid_net_worth", "scenario_delta"],
            "percentiles": [5, 50, 95],
            "include_monthly_columns": True,
            "include_sample_paths": False,
        },
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "label": scenario_id.replace("_", " ").title(),
                "enabled": True,
                "color": "#2563eb",
                "actors": [
                    {"actor_id": "owner", "label": "Owner", "role": "primary_owner"},
                    {"actor_id": "occupant", "label": "Occupant", "role": "equity_building_occupant"},
                ],
                "events": [
                    {
                        "event_id": "purchase",
                        "event_type": "property_purchase",
                        "month_index": 0,
                        "property_id": "sf_ashton",
                        "amount_usd": 998000,
                    }
                ],
                "policies": [
                    {
                        "policy_id": "checking_floor",
                        "policy_type": "checking_floor_sell_public_stock",
                        "actor_id": "owner",
                        "floor_usd": 10000,
                        "sale_amount_usd": 20000,
                    }
                ],
                "property_selection": {
                    "property_id": "sf_ashton",
                    "location_id": "san_francisco_ca",
                    "purchase_price_usd": 998000,
                    "tax_regime": "san_francisco_secured_property_tax",
                },
                "financing": {"financing_mode": "fixed_30", "down_payment_pct": 25, "credit_score": 776},
                "occupancy_plan": {
                    "occupancy_mode": "owner_lives_in_property",
                    "owner_residence_property_id": "sf_ashton",
                    "start_month": 0,
                    "end_month": 36,
                },
                "rental_plan": {
                    "rental_mode": "rent_rooms_while_owner_lives_there",
                    "start_month": 0,
                    "end_month": 36,
                    "room_rent_monthly_usd": 1500,
                    "rooms_rented": 1,
                    "room_vacancy_pct": 5,
                    "management_fee_pct": 0,
                    "leasing_fee_pct": 0,
                },
                "initial_balance_sheet": {
                    "accounts": [
                        {
                            "account_id": "checking",
                            "account_type": "checking",
                            "owner_actor_id": "owner",
                            "balance_usd": 25000,
                        }
                    ],
                    "assets": [
                        {
                            "asset_id": "sp500",
                            "asset_type": "generic_sp500_stock",
                            "owner_actor_id": "owner",
                            "value_usd": 2120000,
                            "cost_basis_usd": 1500000,
                        },
                        {
                            "asset_id": "private_equity",
                            "asset_type": "private_equity",
                            "owner_actor_id": "owner",
                            "value_usd": 0,
                            "units": 23553,
                            "cost_basis_usd": 0,
                        },
                    ],
                    "liabilities": [],
                },
                "tax_regimes": [
                    "california_prop13",
                    "san_francisco_secured_property_tax",
                    "federal_mortgage_interest",
                    "primary_residence_exclusion",
                ],
            }
            for scenario_id in scenario_ids
        ],
    }


def _assert_snake_case_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert _SNAKE_KEY.match(key), key
            _assert_snake_case_keys(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _assert_snake_case_keys(item)


def test_scenario_set_accepts_one_and_two_scenarios_with_typed_enums() -> None:
    scenario_set = ScenarioSet.model_validate(_scenario_set_body("sf_house", "vallejo_house"))

    assert [scenario.scenario_id for scenario in scenario_set.scenarios] == ["sf_house", "vallejo_house"]
    first = scenario_set.scenarios[0]
    assert first.actors[0].role is ActorRole.PRIMARY_OWNER
    assert first.initial_balance_sheet.accounts[0].account_type is AccountType.CHECKING
    assert first.initial_balance_sheet.assets[0].asset_type is AssetType.GENERIC_SP500_STOCK
    assert first.property_selection.property_id == "sf_ashton"
    assert first.property_selection.location_id is LocationId.SAN_FRANCISCO_CA
    assert first.financing.financing_mode is FinancingMode.FIXED_30
    assert first.occupancy_plan.occupancy_mode is OccupancyMode.OWNER_LIVES_IN_PROPERTY
    assert first.rental_plan.rental_mode is RentalMode.RENT_ROOMS_WHILE_OWNER_LIVES_THERE
    assert first.policies[0].policy_type is PolicyType.CHECKING_FLOOR_SELL_PUBLIC_STOCK
    assert TaxRegime.FEDERAL_MORTGAGE_INTEREST in first.tax_regimes


def test_scenario_set_accepts_typed_scenario_economic_assumptions() -> None:
    body = _scenario_set_body("sf_house")
    body["scenarios"][0]["tax_profile"] = {
        "marginal_tax_rate": 37,
        "cap_gains_rate": 28,
        "cap_gains_exclusion_usd": 500_000,
    }
    body["scenarios"][0]["transaction_costs"] = {"closing_cost_buy_pct": 2.5, "closing_cost_sell_pct": 6.5}
    body["scenarios"][0]["property_assumptions"] = {
        "insurance_annual_usd": 1800,
        "maintenance_pct": 1,
        "depreciable_basis_pct": 80,
    }

    scenario_set = ScenarioSet.model_validate(body)

    scenario = scenario_set.scenarios[0]
    assert scenario.tax_profile.marginal_tax_rate == 37
    assert scenario.tax_profile.cap_gains_exclusion_usd == 500_000
    assert scenario.transaction_costs.closing_cost_sell_pct == 6.5
    assert scenario.property_assumptions.insurance_annual_usd == 1800


def test_policy_config_uses_discriminated_rules_and_enums() -> None:
    body = _scenario_set_body("sf_house")
    body["scenarios"][0]["policies"] = [
        {
            "policy_id": "private_equity_sale",
            "policy_type": "private_equity_sale",
            "actor_id": "owner",
            "proceeds_destination": "generic_sp500_stock",
            "sale_rule": {"sale_rule_type": "fixed_amount_on_opportunity", "amount_usd": 50_000},
        },
        {
            "policy_id": "liquidity_reserve",
            "policy_type": "liquidity_reserve",
            "actor_id": "owner",
            "reserve_rule": {
                "reserve_rule_type": "projected_deficits",
                "min_reserve_usd": 10_000,
                "forward_months": 12,
            },
        },
    ]

    scenario = ScenarioSet.model_validate(body).scenarios[0]

    private_equity_policy = scenario.policies[0]
    assert isinstance(private_equity_policy, PrivateEquitySalePolicy)
    assert private_equity_policy.policy_type is PolicyType.PRIVATE_EQUITY_SALE
    assert private_equity_policy.proceeds_destination is PrivateEquitySaleProceedsDestination.GENERIC_SP500_STOCK
    assert isinstance(private_equity_policy.sale_rule, FixedAmountPrivateEquitySaleRule)
    assert private_equity_policy.sale_rule.amount_usd == 50_000
    liquidity_policy = scenario.policies[1]
    assert isinstance(liquidity_policy, LiquidityReservePolicy)
    assert liquidity_policy.policy_type is PolicyType.LIQUIDITY_RESERVE
    assert isinstance(liquidity_policy.reserve_rule, ProjectedDeficitsLiquidityReserveRule)
    assert liquidity_policy.reserve_rule.min_reserve_usd == 10_000
    assert liquidity_policy.reserve_rule.forward_months == 12


def test_scenario_set_model_dump_keeps_backend_keys_snake_case() -> None:
    scenario_set = ScenarioSet.model_validate(_scenario_set_body("sf_house"))

    dumped = scenario_set.model_dump(mode="json")
    _assert_snake_case_keys(dumped)
    assert "scenario_set_id" in dumped
    assert "scenarioSetId" not in dumped


def test_scenario_result_serialization_has_no_projection_compatibility_field() -> None:
    result = ScenarioResult(
        scenario_id="sf_house",
        scenario_label="Sf House",
        status=ScenarioResultStatus.SIMULATED,
        summary=ScenarioAcceptedSummary(
            enabled=True,
            property_id="sf_ashton",
            location_id=LocationId.SAN_FRANCISCO_CA,
            actor_count=1,
            event_count=0,
            policy_count=0,
        ),
    )

    dumped = result.model_dump(mode="json", exclude_none=True)
    assert "projection" not in dumped


def test_scenario_set_rejects_wrong_casing() -> None:
    body = _scenario_set_body("sf_house")
    body["scenarioSetId"] = body.pop("scenario_set_id")

    with pytest.raises(ValidationError):
        ScenarioSet.model_validate(body)

    body = _scenario_set_body("sf_house")
    body["scenarios"][0]["scenarioId"] = body["scenarios"][0].pop("scenario_id")

    with pytest.raises(ValidationError):
        ScenarioSet.model_validate(body)


def test_scenario_set_rejects_legacy_enum_values() -> None:
    body = _scenario_set_body("sf_house")
    body["scenarios"][0]["rental_plan"]["rental_mode"] = "rental_after_3"

    with pytest.raises(ValidationError):
        ScenarioSet.model_validate(body)

    body = _scenario_set_body("sf_house")
    body["scenarios"][0]["occupancy_plan"]["occupancy_mode"] = "live_in"

    with pytest.raises(ValidationError):
        ScenarioSet.model_validate(body)

    body = _scenario_set_body("sf_house")
    body["scenarios"][0]["policies"][0]["policy_type"] = "checking_floor_sp500"

    with pytest.raises(ValidationError):
        ScenarioSet.model_validate(body)

    body = _scenario_set_body("sf_house")
    body["scenarios"][0]["policies"] = [
        {
            "policy_id": "liquidity_reserve",
            "policy_type": "liquidity_reserve",
            "actor_id": "owner",
            "mode": "projected_deficits",
            "min_reserve_usd": 10_000,
            "forward_months": 12,
        }
    ]

    with pytest.raises(ValidationError):
        ScenarioSet.model_validate(body)


def test_scenario_set_rejects_duplicate_scenario_ids() -> None:
    body = _scenario_set_body("same_id", "other_id")
    body["scenarios"][1] = copy.deepcopy(body["scenarios"][0])

    with pytest.raises(ValidationError, match="scenario ids must be unique"):
        ScenarioSet.model_validate(body)


if __name__ == "__main__":
    pytest_bazel.main()
