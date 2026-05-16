from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.core.policy_runtime import (
    actor_policy_programs,
    actor_policy_steps,
    apply_debit_account_instruction,
    apply_generic_sp500_sale_instruction,
    apply_mortgage_payment,
    apply_partner_house_cost_contribution,
    apply_partner_ownership_accrual,
    apply_private_equity_sale_instruction,
    apply_property_operating_cash_flows,
    checking_floor_sell_public_stock_instruction,
    enabled_rules_of_type,
    monthly_spend_debit_instruction,
    partner_contribution_instruction,
    policy_steps_of_type,
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
    LiquidNetWorthFloorPrivateEquitySaleRule,
    MonthlySpendPolicy,
    PartnerEquityAccrualPolicy,
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


def test_actor_policy_steps_make_actor_rule_and_global_order_explicit() -> None:
    scenario = Scenario(
        scenario_id="policy_steps",
        label="Policy Steps",
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
            CheckingFloorSellPublicStockPolicy(
                policy_id="disabled_beta_floor", actor_id="beta", floor_usd=1_000, sale_amount_usd=500, enabled=False
            ),
            PrivateEquitySalePolicy(
                policy_id="beta_private_equity_sale",
                actor_id="beta",
                sale_rule=FixedAmountPrivateEquitySaleRule(amount_usd=50_000),
            ),
        ),
    )

    steps = actor_policy_steps(actor_policy_programs(scenario))

    assert [
        (step.actor_index, step.rule_index, step.sequence_index, step.actor_id, step.policy.policy_id) for step in steps
    ] == [
        (0, 0, 0, "alpha", "alpha_floor"),
        (0, 1, 1, "alpha", "alpha_spend"),
        (1, 0, 2, "beta", "beta_spend"),
        (1, 1, 3, "beta", "beta_private_equity_sale"),
    ]
    assert [step.policy.policy_id for step in policy_steps_of_type(steps, MonthlySpendPolicy)] == [
        "alpha_spend",
        "beta_spend",
    ]
    assert [step.sequence_index for step in policy_steps_of_type(steps, PrivateEquitySalePolicy)] == [3]


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


def test_partner_contribution_instruction_applies_house_costs_and_principal_credit() -> None:
    policy = PartnerEquityAccrualPolicy(policy_id="partner_equity", actor_id="beta", base_monthly_payment_usd=1_000)
    instruction = partner_contribution_instruction(
        policy, recipient_actor_id="alpha", contribution_usd=np.array([0.0, 1_000.0, 3_000.0])
    )

    result = apply_partner_house_cost_contribution(
        instruction,
        house_costs_usd=np.array([0.0, 2_000.0, 2_000.0]),
        mortgage_principal_usd=np.array([0.0, 400.0, 500.0]),
    )

    assert instruction.actor_id == "beta"
    assert instruction.recipient_actor_id == "alpha"
    assert instruction.policy_id == "partner_equity"
    assert instruction.category == "partner_contribution"
    np.testing.assert_allclose(result.contribution_used_usd, [0.0, 1_000.0, 2_000.0])
    np.testing.assert_allclose(result.unallocated_excess_usd, [0.0, 0.0, 1_000.0])
    np.testing.assert_allclose(result.house_cost_share, [0.0, 0.5, 1.0])
    np.testing.assert_allclose(result.principal_credit_usd, [0.0, 200.0, 500.0])
    np.testing.assert_allclose(result.owner_principal_usd, [0.0, 200.0, 0.0])
    assert [(entry.actor_id, entry.domain, entry.category) for entry in result.ledger_entries] == [
        ("beta", "cash", "partner_contribution_transfer"),
        ("alpha", "cash", "partner_contribution_used_for_house_costs"),
        ("alpha", "escrow", "partner_contribution_unallocated"),
        ("beta", "ownership", "partner_principal_credit"),
    ]
    np.testing.assert_allclose(result.ledger_entries[0].amount_usd, [-0.0, -1_000.0, -3_000.0])
    np.testing.assert_allclose(result.ledger_entries[1].amount_usd, [0.0, 1_000.0, 2_000.0])
    np.testing.assert_allclose(result.ledger_entries[2].amount_usd, [0.0, 0.0, 1_000.0])
    np.testing.assert_allclose(result.ledger_entries[3].amount_usd, [0.0, 200.0, 500.0])


def test_partner_ownership_accrual_applies_freeze_and_records_ledgers() -> None:
    policy = PartnerEquityAccrualPolicy(policy_id="partner_equity", actor_id="beta", base_monthly_payment_usd=1_000)
    transfer = partner_contribution_instruction(
        policy,
        recipient_actor_id="alpha",
        contribution_usd=np.array([[0.0, 1_000.0, 1_000.0, 1_000.0]], dtype="float64"),
    )

    result = apply_partner_ownership_accrual(
        transfer,
        owner_initial_equity_usd=20_000,
        home_equity_usd=np.array([[20_000.0, 20_600.0, 21_200.0, 24_000.0]], dtype="float64"),
        owner_principal_usd=np.array([[0.0, 300.0, 300.0, 300.0]], dtype="float64"),
        partner_principal_credit_usd=np.array([[0.0, 100.0, 100.0, 100.0]], dtype="float64"),
        month_index=np.array([0, 1, 2, 3]),
        freeze_after_month=2,
    )

    expected_partner_ledger = np.array([[0.0, 100.0, 200.0, 300.0]], dtype="float64")
    expected_owner_ledger = np.array([[20_000.0, 20_300.0, 20_600.0, 20_900.0]], dtype="float64")
    expected_frozen_pct = 200 / 20_800
    np.testing.assert_allclose(result.partner_equity_ledger_usd, expected_partner_ledger)
    np.testing.assert_allclose(result.owner_equity_ledger_usd, expected_owner_ledger)
    np.testing.assert_allclose(result.ownership_pct[0, 2:], expected_frozen_pct)
    np.testing.assert_allclose(result.home_equity_claim_usd[0, 3], 24_000 * expected_frozen_pct)
    np.testing.assert_allclose(
        result.owner_home_equity_claim_usd + result.home_equity_claim_usd, [[20_000.0, 20_600.0, 21_200.0, 24_000.0]]
    )
    ledger_shape = [
        (entry.actor_id, entry.domain, entry.category, entry.counterparty_actor_id) for entry in result.ledger_entries
    ]
    assert ledger_shape == [
        ("beta", "ownership", "partner_principal_credit", "alpha"),
        ("alpha", "ownership", "owner_principal_credit", "beta"),
    ]
    snapshot_shape = [
        (snapshot.actor_id, snapshot.domain, snapshot.category, snapshot.counterparty_actor_id)
        for snapshot in result.balance_snapshots
    ]
    assert snapshot_shape == [
        ("beta", "ownership", "partner_equity_ledger", "alpha"),
        ("alpha", "ownership", "owner_equity_ledger", "beta"),
        ("beta", "ownership", "partner_home_equity_claim", "alpha"),
        ("alpha", "ownership", "owner_home_equity_claim", "beta"),
    ]
    np.testing.assert_allclose(result.balance_snapshots[0].amount_usd, expected_partner_ledger)
    np.testing.assert_allclose(result.balance_snapshots[1].amount_usd, expected_owner_ledger)


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
        sale_opportunity_mask=np.array([False, True]),
        private_equity_value_before_sale_usd=np.array([200_000.0, 200_000.0]),
        path_set_id="path_set:test:seed:7:rollouts:2:horizon_months:3",
        month_index=2,
        source_holding_id="pe",
    )
    instruction = private_equity_sale_instruction(
        policy, opportunity=opportunity, liquid_net_worth_usd=np.array([100_000.0, 100_000.0])
    )

    result = apply_private_equity_sale_instruction(
        instruction,
        opportunity=opportunity,
        remaining_basis_usd=np.array([80_000.0, 80_000.0]),
        remaining_units=np.array([100.0, 100.0]),
        remaining_fraction=np.array([1.0, 1.0]),
        cap_gains_rate_pct=20,
    )

    assert instruction.proceeds_destination is AccountType.CHECKING
    assert instruction.opportunity_id.tolist() == [
        None,
        "path_set:test:seed:7:rollouts:2:horizon_months:3:path:1:month:2:private_equity_holding:pe:sale_opportunity",
    ]
    assert instruction.opportunity_cause_id.tolist() == [
        "path_set:test:seed:7:rollouts:2:horizon_months:3:path:0:month:2:private_equity_holding:pe:no_sale_opportunity",
        "path_set:test:seed:7:rollouts:2:horizon_months:3:path:1:month:2:private_equity_holding:pe:sale_opportunity",
    ]
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


def test_private_equity_liquid_net_worth_floor_rule_uses_opportunity_and_liquid_assets() -> None:
    policy = PrivateEquitySalePolicy(
        policy_id="pe_sale",
        actor_id="alpha",
        proceeds_destination="generic_sp500_stock",
        sale_rule=LiquidNetWorthFloorPrivateEquitySaleRule(min_liquid_net_worth_usd=100_000, sale_amount_usd=50_000),
    )
    opportunity = private_equity_sale_opportunity(
        sale_opportunity_mask=np.array([False, True, True]),
        private_equity_value_before_sale_usd=np.array([200_000.0, 200_000.0, 200_000.0]),
        path_set_id="path_set:test:seed:7:rollouts:3:horizon_months:3",
        month_index=1,
        source_holding_id="pe",
    )

    instruction = private_equity_sale_instruction(
        policy, opportunity=opportunity, liquid_net_worth_usd=np.array([50_000.0, 90_000.0, 120_000.0])
    )

    assert instruction.proceeds_destination is AssetType.GENERIC_SP500_STOCK
    np.testing.assert_allclose(instruction.requested_amount_usd, [0.0, 50_000.0, 0.0])
    assert instruction.opportunity_id.tolist() == [
        None,
        "path_set:test:seed:7:rollouts:3:horizon_months:3:path:1:month:1:private_equity_holding:pe:sale_opportunity",
        "path_set:test:seed:7:rollouts:3:horizon_months:3:path:2:month:1:private_equity_holding:pe:sale_opportunity",
    ]


if __name__ == "__main__":
    pytest_bazel.main()
