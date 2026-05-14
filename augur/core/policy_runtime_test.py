from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.core.policy_runtime import (
    actor_policy_programs,
    apply_debit_account_instruction,
    apply_generic_sp500_sale_instruction,
    apply_mortgage_payment,
    apply_private_equity_sale_instruction,
    apply_property_operating_cash_flows,
    checking_floor_sell_public_stock_instruction,
    enabled_rules_of_type,
    monthly_spend_debit_instruction,
    private_equity_sale_instruction,
    private_equity_sale_opportunity,
)
from augur.core.scenario_set import (
    AccountType,
    Actor,
    ActorRole,
    AssetType,
    CheckingFloorSellPublicStockPolicy,
    FixedAmountPrivateEquitySaleRule,
    MonthlySpendPolicy,
    PrivateEquitySalePolicy,
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


def test_mortgage_payment_application_records_cash_and_liability_ledger() -> None:
    result = apply_mortgage_payment(
        actor_id="alpha",
        policy_id="mortgage_servicing",
        mortgage_payment_usd=np.array([0.0, 2_500.0]),
        mortgage_interest_usd=np.array([0.0, 2_000.0]),
        mortgage_principal_usd=np.array([0.0, 500.0]),
        mortgage_balance_after_usd=np.array([400_000.0, 399_500.0]),
    )

    assert result.actor_id == "alpha"
    assert result.policy_id == "mortgage_servicing"
    np.testing.assert_allclose(result.mortgage_payment_usd, [0.0, 2_500.0])
    np.testing.assert_allclose(result.mortgage_interest_usd, [0.0, 2_000.0])
    np.testing.assert_allclose(result.mortgage_principal_usd, [0.0, 500.0])
    np.testing.assert_allclose(result.mortgage_balance_after_usd, [400_000.0, 399_500.0])
    assert [(entry.domain, entry.category) for entry in result.ledger_entries] == [
        ("cash", "mortgage_interest"),
        ("cash", "mortgage_principal"),
        ("liability", "mortgage_principal"),
    ]
    np.testing.assert_allclose(result.ledger_entries[0].amount_usd, [-0.0, -2_000.0])
    np.testing.assert_allclose(result.ledger_entries[1].amount_usd, [-0.0, -500.0])
    np.testing.assert_allclose(result.ledger_entries[2].amount_usd, [-0.0, -500.0])


def test_property_operating_cash_flow_application_records_cash_ledger() -> None:
    result = apply_property_operating_cash_flows(
        actor_id="alpha",
        policy_id="property_operating_cash_flow",
        property_tax_usd=np.array([0.0, 100.0]),
        hoa_usd=np.array([0.0, 25.0]),
        insurance_usd=np.array([0.0, 50.0]),
        maintenance_usd=np.array([0.0, 75.0]),
        rental_gross_income_usd=np.array([0.0, 2_000.0]),
        rental_vacancy_loss_usd=np.array([0.0, 100.0]),
        rental_income_usd=np.array([0.0, 1_900.0]),
        rental_management_fee_usd=np.array([0.0, 152.0]),
        rental_leasing_fee_usd=np.array([0.0, 40.0]),
    )

    assert result.actor_id == "alpha"
    assert result.policy_id == "property_operating_cash_flow"
    np.testing.assert_allclose(result.property_carrying_cost_usd, [0.0, 442.0])
    np.testing.assert_allclose(result.net_operating_cash_flow_usd, [0.0, 1_458.0])
    assert [(entry.domain, entry.category) for entry in result.ledger_entries] == [
        ("rental", "rental_gross_income"),
        ("rental", "rental_vacancy_loss"),
        ("cash", "rental_income"),
        ("cash", "property_tax"),
        ("cash", "hoa"),
        ("cash", "insurance"),
        ("cash", "maintenance"),
        ("cash", "rental_management_fee"),
        ("cash", "rental_leasing_fee"),
    ]
    np.testing.assert_allclose(result.ledger_entries[2].amount_usd, [0.0, 1_900.0])
    np.testing.assert_allclose(result.ledger_entries[3].amount_usd, [-0.0, -100.0])
    np.testing.assert_allclose(result.ledger_entries[8].amount_usd, [-0.0, -40.0])


def test_private_equity_fixed_rule_uses_opportunity_and_records_ledger() -> None:
    policy = PrivateEquitySalePolicy(
        policy_id="pe_sale", actor_id="alpha", sale_rule=FixedAmountPrivateEquitySaleRule(amount_usd=50_000)
    )
    opportunity = private_equity_sale_opportunity(
        liquidity_event_mask=np.array([False, True]),
        private_equity_value_before_sale_usd=np.array([200_000.0, 200_000.0]),
    )
    instruction = private_equity_sale_instruction(policy, request=None, opportunity=opportunity)

    result = apply_private_equity_sale_instruction(
        instruction,
        opportunity=opportunity,
        remaining_basis_usd=np.array([80_000.0, 80_000.0]),
        remaining_units=np.array([100.0, 100.0]),
        remaining_fraction=np.array([1.0, 1.0]),
        cap_gains_rate_pct=20,
    )

    assert instruction.proceeds_destination is AccountType.CHECKING
    np.testing.assert_allclose(instruction.requested_amount_usd, [0.0, 50_000.0])
    np.testing.assert_allclose(result.sale_usd, [0.0, 50_000.0])
    np.testing.assert_allclose(result.basis_usd, [0.0, 20_000.0])
    np.testing.assert_allclose(result.taxable_gain_usd, [0.0, 30_000.0])
    np.testing.assert_allclose(result.estimated_tax_usd, [0.0, 6_000.0])
    np.testing.assert_allclose(result.after_tax_proceeds_usd, [0.0, 44_000.0])
    np.testing.assert_allclose(result.sold_units, [0.0, 25.0])
    np.testing.assert_allclose(result.sold_fraction, [0.0, 0.25])
    np.testing.assert_allclose(result.remaining_units, [100.0, 75.0])
    np.testing.assert_allclose(result.remaining_basis_usd, [80_000.0, 60_000.0])
    np.testing.assert_allclose(result.remaining_fraction, [1.0, 0.75])
    assert [entry.category for entry in result.ledger_entries] == [
        "private_equity_sale",
        "private_equity_capital_gains_tax",
        "private_equity_after_tax_proceeds",
    ]
    np.testing.assert_allclose(result.ledger_entries[0].amount_usd, [0.0, -50_000.0])
    np.testing.assert_allclose(result.ledger_entries[1].amount_usd, [-0.0, -6_000.0])
    np.testing.assert_allclose(result.ledger_entries[2].amount_usd, [0.0, 44_000.0])


if __name__ == "__main__":
    pytest_bazel.main()
