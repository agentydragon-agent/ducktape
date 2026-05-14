from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.core.policy_runtime import (
    actor_policy_programs,
    apply_debit_account_instruction,
    apply_generic_sp500_sale_instruction,
    checking_floor_sell_public_stock_instruction,
    enabled_rules_of_type,
    monthly_spend_debit_instruction,
)
from augur.core.scenario_set import (
    AccountType,
    Actor,
    ActorRole,
    AssetType,
    CheckingFloorSellPublicStockPolicy,
    MonthlySpendPolicy,
    Scenario,
)


def test_actor_policy_programs_preserve_actor_order_and_enabled_rule_order() -> None:
    scenario = Scenario(
        scenario_id="policy_order",
        label="Policy Order",
        actors=(
            Actor(actor_id="alpha", label="Alpha", role=ActorRole.PRIMARY_OWNER),
            Actor(actor_id="beta", label="Beta", role=ActorRole.EQUITY_BUILDING_OCCUPANT),
        ),
        policies=(
            MonthlySpendPolicy(policy_id="beta_spend", actor_id="beta", monthly_spend_usd=100),
            MonthlySpendPolicy(
                policy_id="disabled_alpha_spend", actor_id="alpha", monthly_spend_usd=100, enabled=False
            ),
            CheckingFloorSellPublicStockPolicy(
                policy_id="alpha_floor", actor_id="alpha", floor_usd=1_000, sale_amount_usd=500
            ),
            MonthlySpendPolicy(policy_id="alpha_spend", actor_id="alpha", monthly_spend_usd=200),
        ),
    )

    programs = actor_policy_programs(scenario)

    assert [(program.actor_id, [rule.policy_id for rule in program.rules]) for program in programs] == [
        ("alpha", ["alpha_floor", "alpha_spend"]),
        ("beta", ["beta_spend"]),
    ]
    assert [rule.policy_id for rule in enabled_rules_of_type(programs, CheckingFloorSellPublicStockPolicy)] == [
        "alpha_floor"
    ]


def test_checking_floor_instruction_applier_clips_sale_and_records_shortfall() -> None:
    policy = CheckingFloorSellPublicStockPolicy(
        policy_id="checking_floor", actor_id="alpha", floor_usd=100, sale_amount_usd=80
    )
    current_cash = np.array([50.0, 90.0, 150.0])
    instruction = checking_floor_sell_public_stock_instruction(policy, current_cash_usd=current_cash)

    result = apply_generic_sp500_sale_instruction(
        instruction,
        current_cash_usd=current_cash,
        remaining_units=np.array([40.0, 200.0, 200.0]),
        remaining_basis_usd=np.array([20.0, 100.0, 100.0]),
        sp500_unit_price_usd=np.ones(3, dtype="float64"),
    )

    assert instruction.asset_type is AssetType.GENERIC_SP500_STOCK
    np.testing.assert_allclose(instruction.requested_amount_usd, [80.0, 80.0, 0.0])
    np.testing.assert_allclose(result.sale_usd, [40.0, 80.0, 0.0])
    np.testing.assert_allclose(result.basis_usd, [20.0, 40.0, 0.0])
    np.testing.assert_allclose(result.gain_usd, [20.0, 40.0, 0.0])
    np.testing.assert_allclose(result.current_cash_usd, [90.0, 170.0, 150.0])
    np.testing.assert_allclose(result.remaining_units, [0.0, 120.0, 200.0])
    np.testing.assert_allclose(result.remaining_basis_usd, [0.0, 60.0, 100.0])
    np.testing.assert_allclose(result.shortfall_usd, [10.0, 0.0, 0.0])


def test_monthly_spend_instruction_applier_debits_cash_and_records_ledger() -> None:
    policy = MonthlySpendPolicy(
        policy_id="living_expenses", actor_id="alpha", monthly_spend_usd=100, inflation_adjusted=True
    )
    decision = monthly_spend_debit_instruction(policy, inflation_multiplier=np.array([1.0, 1.2, 1.5]))

    result = apply_debit_account_instruction(decision.debit, current_cash_usd=np.array([1_000.0, 500.0, 50.0]))

    assert decision.debit.account_type is AccountType.CHECKING
    assert decision.debit.category == "monthly_spend"
    np.testing.assert_allclose(decision.inflation_multiplier, [1.0, 1.2, 1.5])
    np.testing.assert_allclose(result.debit_usd, [100.0, 120.0, 150.0])
    np.testing.assert_allclose(result.current_cash_usd, [900.0, 380.0, -100.0])
    assert len(result.ledger_entries) == 1
    spend_ledger = result.ledger_entries[0]
    assert spend_ledger.actor_id == "alpha"
    assert spend_ledger.policy_id == "living_expenses"
    assert spend_ledger.domain == "cash"
    assert spend_ledger.category == "monthly_spend"
    np.testing.assert_allclose(spend_ledger.amount_usd, [-100.0, -120.0, -150.0])


if __name__ == "__main__":
    pytest_bazel.main()
