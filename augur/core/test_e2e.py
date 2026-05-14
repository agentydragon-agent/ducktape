"""E2e tests that exercise the augur simulation core in isolation.

These tests construct scenarios programmatically, run them through
the core engine with a deterministic market provider, and assert on financial
outcomes — no webapp, no FastAPI, no config files. Each test spells out the
expected computation so the test itself documents what the simulator should
produce.
"""

from __future__ import annotations

import numpy as np
import pytest
import pytest_bazel
from pydantic import ValidationError

from augur.core.api import ScenarioRun, simulate_set
from augur.core.local_regulation import LocationId
from augur.core.market_bundle_test_support import NoopMarketBundleProvider
from augur.core.scenario_set import (
    AccountBalance,
    AccountType,
    AccruePartnerEquityAction,
    Actor,
    ActorRole,
    AssetType,
    CheckingFloorSellPublicStockPolicy,
    Financing,
    FinancingMode,
    FixedAmountPrivateEquitySaleRule,
    GenericSp500StockPosition,
    InitialBalanceSheet,
    MarketRequest,
    MonthlySpendAction,
    MonthlySpendPolicy,
    PartnerEquityAccrualPolicy,
    PayMortgageAction,
    PrivateEquityPosition,
    PrivateEquitySalePolicy,
    PrivateEquitySaleRequestEvent,
    PropertyAssumptions,
    PropertySaleEvent,
    PropertySelection,
    RentalMode,
    Scenario,
    ScenarioSet,
    SellPrivateEquityAction,
    SellSp500Action,
    SettlePropertySaleAction,
    TaxProfile,
    TransactionCosts,
    TransferPartnerContributionAction,
    WholePropertyRentalPlan,
)


def _run_scenario(
    scenario: Scenario,
    *,
    rollout_count: int = 1,
    horizon_months: int = 12,
    market_provider: NoopMarketBundleProvider | None = None,
) -> ScenarioRun:
    market_request = MarketRequest(
        market_model_id="e2e_noop", rollout_count=rollout_count, horizon_months=horizon_months, random_seed=0
    )
    scenario_set = ScenarioSet(
        scenario_set_id=f"{scenario.scenario_id}_set",
        title=f"{scenario.label} Set",
        market_request=market_request,
        scenarios=(scenario,),
    )
    run = simulate_set(scenario_set, market_provider=market_provider or NoopMarketBundleProvider())
    return run.scenario(scenario.scenario_id)


def _simple_actor() -> Actor:
    return Actor(actor_id="alpha", label="Alpha", role=ActorRole.PRIMARY_OWNER)


def _cash_only_scenario(*, cash_usd: float, scenario_id: str = "e2e") -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        label=scenario_id.replace("_", " ").title(),
        actors=(_simple_actor(),),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking",
                    account_type=AccountType.CHECKING,
                    owner_actor_id="alpha",
                    balance_usd=cash_usd,
                ),
            )
        ),
    )


def test_cash_only_no_activity_preserves_balance() -> None:
    """Agent holds $100k in checking, no property, no investments, no spending.
    Flat market. Cash should remain exactly $100k at every month."""
    scenario = _cash_only_scenario(cash_usd=100_000)
    result = _run_scenario(scenario, horizon_months=12)

    # Single rollout, 13 months (0..12)
    assert result.matrix("cash_usd").shape == (1, 13)
    np.testing.assert_allclose(result.series("cash_usd"), 100_000)
    np.testing.assert_allclose(result.matrix("generic_sp500_value_usd"), 0)
    np.testing.assert_allclose(result.matrix("private_equity_value_usd"), 0)
    np.testing.assert_allclose(result.matrix("property_value_usd"), 0)
    np.testing.assert_allclose(result.series("net_worth_usd"), 100_000)


def test_simulate_set_rejects_policy_with_unknown_actor_path() -> None:
    """The public API validates scenario references before entering the engine."""
    scenario = _cash_only_scenario(cash_usd=100_000).model_copy(
        update={
            "policies": (MonthlySpendPolicy(policy_id="living_expenses", actor_id="ghost", monthly_spend_usd=5_000),)
        }
    )

    with pytest.raises(ValueError, match=r"scenarios\[0\]\.policies\[0\]\.actor_id references unknown actor 'ghost'"):
        _run_scenario(scenario, horizon_months=12)


def test_simulate_set_rejects_partner_equity_policy_for_other_property() -> None:
    """Property-specific partner-equity policies must name the selected property."""
    scenario = Scenario(
        scenario_id="invalid_partner_property",
        label="Invalid Partner Property",
        actors=(_simple_actor(), Actor(actor_id="beta", label="Beta", role=ActorRole.EQUITY_BUILDING_OCCUPANT)),
        property_selection=PropertySelection(
            property_id="test_property", location_id=LocationId.VALLEJO_CA, purchase_price_usd=100_000
        ),
        policies=(
            PartnerEquityAccrualPolicy(
                policy_id="partner_equity",
                actor_id="beta",
                property_id="other_property",
                base_monthly_payment_usd=1_000,
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"scenarios\[0\]\.policies\[0\]\.property_id references 'other_property', "
        r"but scenario selects 'test_property'",
    ):
        _run_scenario(scenario, horizon_months=12)


def test_sp500_only_grows_with_market() -> None:
    """Agent holds $50k in SP500 (basis = $50k), no cash, no property.
    SP500 multiplier goes: 1.0, 1.1, 1.2, 1.3 (monthly, not annualized).
    After 3 months the SP500 position should be $50k * 1.3 = $65k."""
    scenario = Scenario(
        scenario_id="sp500_growth",
        label="SP500 Growth",
        actors=(_simple_actor(),),
        initial_balance_sheet=InitialBalanceSheet(
            assets=(
                GenericSp500StockPosition(
                    asset_id="sp500",
                    asset_type=AssetType.GENERIC_SP500_STOCK,
                    owner_actor_id="alpha",
                    value_usd=50_000,
                    cost_basis_usd=50_000,
                ),
            )
        ),
    )
    sp500_path = (1.0, 1.1, 1.2, 1.3)
    result = _run_scenario(scenario, horizon_months=3, market_provider=NoopMarketBundleProvider(sp500_path=sp500_path))

    assert result.matrix("cash_usd").shape == (1, 4)
    np.testing.assert_allclose(result.series("cash_usd"), 0)
    # SP500 value tracks multiplier: 50k * [1.0, 1.1, 1.2, 1.3]
    np.testing.assert_allclose(result.series("generic_sp500_value_usd"), [50_000, 55_000, 60_000, 65_000])
    # Net worth = SP500 only
    np.testing.assert_allclose(result.series("net_worth_usd"), [50_000, 55_000, 60_000, 65_000])


def test_cash_and_sp500_combined_net_worth() -> None:
    """Agent holds $30k cash + $70k SP500. Flat market (all 1.0).
    Net worth should be $100k at every month."""
    scenario = Scenario(
        scenario_id="mixed",
        label="Mixed",
        actors=(_simple_actor(),),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking", account_type=AccountType.CHECKING, owner_actor_id="alpha", balance_usd=30_000
                ),
            ),
            assets=(
                GenericSp500StockPosition(
                    asset_id="sp500",
                    asset_type=AssetType.GENERIC_SP500_STOCK,
                    owner_actor_id="alpha",
                    value_usd=70_000,
                    cost_basis_usd=70_000,
                ),
            ),
        ),
    )
    result = _run_scenario(scenario, horizon_months=6)

    np.testing.assert_allclose(result.series("cash_usd"), 30_000)
    np.testing.assert_allclose(result.series("generic_sp500_value_usd"), 70_000)
    np.testing.assert_allclose(result.series("net_worth_usd"), 100_000)


def test_monthly_spend_drains_cash() -> None:
    """Agent starts with $100k cash, spends $5k/month. Flat market.
    Month 0: $100k. Month 1: $95k. ... Month 12: $40k."""
    scenario = Scenario(
        scenario_id="spend_down",
        label="Spend Down",
        actors=(_simple_actor(),),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking",
                    account_type=AccountType.CHECKING,
                    owner_actor_id="alpha",
                    balance_usd=100_000,
                ),
            )
        ),
        policies=(MonthlySpendPolicy(policy_id="living_expenses", actor_id="alpha", monthly_spend_usd=5_000),),
    )
    result = _run_scenario(scenario, horizon_months=12)

    # Month 0: initial $100k (spend applies from month 1 onward)
    np.testing.assert_allclose(result.series("cash_usd")[0], 100_000)
    # Month 1: 100k - 5k = 95k
    np.testing.assert_allclose(result.series("cash_usd")[1], 95_000)
    # Month 6: 100k - 6*5k = 70k
    np.testing.assert_allclose(result.series("cash_usd")[6], 70_000)
    # Month 12: 100k - 12*5k = 40k
    np.testing.assert_allclose(result.terminal("cash_usd"), 40_000)
    # Verify spend array
    np.testing.assert_allclose(result.series("monthly_spend_usd")[0], 0)
    np.testing.assert_allclose(result.series("monthly_spend_usd")[1], 5_000)
    np.testing.assert_allclose(result.series("monthly_spend_usd")[12], 5_000)
    # Verify actions recorded for each month 1..12
    spend_actions = result.actions(MonthlySpendAction)
    assert len(spend_actions) == 12
    assert spend_actions[0].amount_usd == 5_000
    assert spend_actions[0].month_index == 1


def test_monthly_spend_records_each_rollout_and_month() -> None:
    """A spend policy emits an action for every rollout where spend applies."""
    scenario = Scenario(
        scenario_id="multi_rollout_spend",
        label="Multi Rollout Spend",
        actors=(_simple_actor(),),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking",
                    account_type=AccountType.CHECKING,
                    owner_actor_id="alpha",
                    balance_usd=100_000,
                ),
            )
        ),
        policies=(MonthlySpendPolicy(policy_id="living_expenses", actor_id="alpha", monthly_spend_usd=5_000),),
    )
    result = _run_scenario(scenario, rollout_count=2, horizon_months=2)

    np.testing.assert_allclose(result.matrix("cash_usd")[:, 0], 100_000)
    np.testing.assert_allclose(result.matrix("cash_usd")[:, 1], 95_000)
    np.testing.assert_allclose(result.matrix("cash_usd")[:, 2], 90_000)
    np.testing.assert_allclose(result.matrix("monthly_spend_usd")[:, 1:], 5_000)
    assert [
        (action.rollout_index, action.month_index, action.amount_usd) for action in result.actions(MonthlySpendAction)
    ] == [(0, 1, 5_000), (1, 1, 5_000), (0, 2, 5_000), (1, 2, 5_000)]


def test_fixed_rate_mortgage_amortizes_and_purchase_cash_outlay_posts_at_month_zero() -> None:
    """Agent buys a $500k property with 20% down and 30-year fixed financing at 6%.
    Month 0 records the down payment plus buy-side closing costs. Month 1
    mortgage interest and principal match the standard amortization formula."""
    scenario = Scenario(
        scenario_id="mortgage_amortization",
        label="Mortgage Amortization",
        actors=(_simple_actor(),),
        property_selection=PropertySelection(
            property_id="test_property", location_id=LocationId.SAN_FRANCISCO_CA, purchase_price_usd=500_000
        ),
        financing=Financing(financing_mode=FinancingMode.FIXED_30, down_payment_pct=20, mortgage_rate_pct=6),
        transaction_costs=TransactionCosts(closing_cost_buy_pct=2.5, closing_cost_sell_pct=0),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking",
                    account_type=AccountType.CHECKING,
                    owner_actor_id="alpha",
                    balance_usd=100_000,
                ),
            )
        ),
    )

    result = _run_scenario(scenario, horizon_months=12)

    loan_amount = 400_000
    monthly_rate = 0.06 / 12
    payment = loan_amount * monthly_rate * (1 + monthly_rate) ** 360 / ((1 + monthly_rate) ** 360 - 1)
    expected_month_1_interest = 2_000
    expected_month_1_principal = payment - expected_month_1_interest
    rollout = result.rollout(0)
    np.testing.assert_allclose(rollout.series("cash_usd")[0], -12_500)
    np.testing.assert_allclose(rollout.series("property_value_usd")[0], 500_000)
    np.testing.assert_allclose(rollout.series("mortgage_balance_usd")[0], loan_amount)
    np.testing.assert_allclose(rollout.series("mortgage_interest_usd")[1], expected_month_1_interest)
    np.testing.assert_allclose(rollout.series("mortgage_principal_usd")[1], expected_month_1_principal)
    np.testing.assert_allclose(rollout.series("mortgage_payment_usd")[1], payment)
    np.testing.assert_allclose(rollout.series("mortgage_balance_usd")[1], loan_amount - expected_month_1_principal)
    mortgage_payments = result.actions(PayMortgageAction)
    assert len(mortgage_payments) == 12
    assert mortgage_payments[0].month_index == 1
    assert mortgage_payments[0].actor_id == "alpha"
    assert mortgage_payments[0].policy_id == "mortgage_servicing"
    np.testing.assert_allclose(mortgage_payments[0].mortgage_payment_usd, payment)
    np.testing.assert_allclose(mortgage_payments[0].mortgage_interest_usd, expected_month_1_interest)
    np.testing.assert_allclose(mortgage_payments[0].mortgage_principal_usd, expected_month_1_principal)
    np.testing.assert_allclose(
        mortgage_payments[0].mortgage_balance_after_usd, loan_amount - expected_month_1_principal
    )


def test_partner_equity_accrual_records_contributions_and_claims() -> None:
    """A partner contribution policy acts like a housing-cost contribution program.

    The partner sends cash every occupied month. Contributions are applied to
    house costs first, and the portion covering mortgage principal increases the
    partner's equity claim.
    """
    purchase_price = 100_000
    down_payment_pct = 20
    down_payment = purchase_price * down_payment_pct / 100
    loan_amount = purchase_price - down_payment
    monthly_principal = loan_amount / (30 * 12)
    horizon_months = 60

    scenario = Scenario(
        scenario_id="partner_equity_accrual",
        label="Partner Equity Accrual",
        actors=(_simple_actor(), Actor(actor_id="beta", label="Beta", role=ActorRole.EQUITY_BUILDING_OCCUPANT)),
        property_selection=PropertySelection(
            property_id="test_property", location_id=LocationId.VALLEJO_CA, purchase_price_usd=purchase_price
        ),
        financing=Financing(
            financing_mode=FinancingMode.FIXED_30, down_payment_pct=down_payment_pct, mortgage_rate_pct=0
        ),
        transaction_costs=TransactionCosts(closing_cost_buy_pct=0, closing_cost_sell_pct=0),
        property_assumptions=PropertyAssumptions(insurance_annual_usd=0, maintenance_pct=0),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking", account_type=AccountType.CHECKING, owner_actor_id="alpha", balance_usd=40_000
                ),
            )
        ),
        policies=(
            PartnerEquityAccrualPolicy(
                policy_id="partner_equity",
                actor_id="beta",
                property_id="test_property",
                base_monthly_payment_usd=1_000,
                occupied_months=horizon_months,
                grow_with_inflation=False,
            ),
        ),
    )

    result = _run_scenario(scenario, horizon_months=horizon_months)

    partner_principal_credit = monthly_principal * horizon_months
    expected_owner_ledger = down_payment
    expected_partner_ledger = partner_principal_credit
    expected_ownership_pct = expected_partner_ledger / (expected_owner_ledger + expected_partner_ledger)
    expected_terminal_mortgage_balance = loan_amount - partner_principal_credit
    expected_home_equity = purchase_price - expected_terminal_mortgage_balance
    rollout = result.rollout(0)

    np.testing.assert_allclose(rollout.series("partner_contribution_usd")[0], 0)
    np.testing.assert_allclose(rollout.series("partner_contribution_usd")[1:], 1_000)
    assert np.all(rollout.series("partner_unallocated_excess_usd")[1:] > 0)
    assert np.all(rollout.series("partner_house_costs_usd")[1:] > monthly_principal)
    np.testing.assert_allclose(rollout.series("partner_principal_credit_usd")[1:], monthly_principal)
    np.testing.assert_allclose(rollout.series("owner_principal_credit_usd")[1:], 0)
    np.testing.assert_allclose(rollout.series("partner_equity_ledger_usd")[60], expected_partner_ledger)
    np.testing.assert_allclose(rollout.series("owner_equity_ledger_usd")[60], expected_owner_ledger)
    np.testing.assert_allclose(rollout.series("partner_ownership_pct")[60], expected_ownership_pct)
    np.testing.assert_allclose(rollout.series("mortgage_balance_usd")[60], expected_terminal_mortgage_balance)
    np.testing.assert_allclose(rollout.series("home_equity_usd")[60], expected_home_equity)
    np.testing.assert_allclose(rollout.series("partner_home_equity_claim_usd")[60], expected_partner_ledger)
    np.testing.assert_allclose(rollout.series("owner_home_equity_claim_usd")[60], expected_owner_ledger)
    np.testing.assert_allclose(
        rollout.series("partner_home_equity_claim_usd")[60] + rollout.series("owner_home_equity_claim_usd")[60],
        expected_home_equity,
    )
    np.testing.assert_allclose(rollout.series("cash_usd")[0], 20_000)
    np.testing.assert_allclose(rollout.series("cash_usd")[60], 20_000)

    transfers = result.actions(TransferPartnerContributionAction)
    assert len(transfers) == horizon_months
    assert transfers[0].month_index == 1
    assert transfers[-1].month_index == horizon_months
    assert all(action.actor_id == "beta" for action in transfers)
    assert all(action.recipient_actor_id == "alpha" for action in transfers)
    assert all(action.amount_usd == 1_000 for action in transfers)
    np.testing.assert_allclose(
        [action.applied_to_house_costs_usd for action in transfers], rollout.series("partner_contribution_used_usd")[1:]
    )
    assert all(action.unallocated_amount_usd > 0 for action in transfers)

    mortgage_payments = result.actions(PayMortgageAction)
    assert len(mortgage_payments) == horizon_months
    assert mortgage_payments[0].actor_id == "alpha"
    np.testing.assert_allclose(mortgage_payments[0].mortgage_principal_usd, monthly_principal)
    np.testing.assert_allclose(mortgage_payments[-1].mortgage_balance_after_usd, expected_terminal_mortgage_balance)

    accruals = result.actions(AccruePartnerEquityAction)
    assert len(accruals) == horizon_months
    assert accruals[0].actor_id == "beta"
    assert accruals[0].beneficiary_actor_id == "beta"
    assert accruals[0].property_id == "test_property"
    np.testing.assert_allclose(accruals[0].principal_credit_usd, monthly_principal)
    np.testing.assert_allclose(accruals[-1].ownership_pct_after, expected_ownership_pct)
    np.testing.assert_allclose(accruals[-1].home_equity_claim_usd_after, expected_partner_ledger)


def test_property_sale_records_capital_gains_tax_and_net_proceeds() -> None:
    """A property sale records closing costs, the primary-residence exclusion,
    capital-gains tax, and net proceeds as part of the simulated cash-flow
    truth."""
    scenario = Scenario(
        scenario_id="property_sale_tax",
        label="Property Sale Tax",
        actors=(_simple_actor(),),
        events=(PropertySaleEvent(event_id="sale", month_index=60, property_id="test_property"),),
        property_selection=PropertySelection(
            property_id="test_property", location_id=LocationId.SAN_FRANCISCO_CA, purchase_price_usd=500_000
        ),
        financing=Financing(financing_mode=FinancingMode.CASH),
        transaction_costs=TransactionCosts(closing_cost_buy_pct=0, closing_cost_sell_pct=6.5),
        tax_profile=TaxProfile(cap_gains_exclusion_usd=250_000, cap_gains_rate=20),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking",
                    account_type=AccountType.CHECKING,
                    owner_actor_id="alpha",
                    balance_usd=500_000,
                ),
            )
        ),
    )
    sale_value = 900_000
    result = _run_scenario(
        scenario,
        horizon_months=60,
        market_provider=NoopMarketBundleProvider(home_path=tuple(np.linspace(1.0, sale_value / 500_000, 61))),
    )

    sale_closing_cost = sale_value * 0.065
    realized_gain = sale_value - sale_closing_cost - 500_000
    taxable_gain = realized_gain - 250_000
    sale_tax = taxable_gain * 0.20
    rollout = result.rollout(0)
    np.testing.assert_allclose(rollout.series("property_sale_gross_usd")[60], sale_value)
    np.testing.assert_allclose(rollout.series("sale_closing_cost_usd")[60], sale_closing_cost)
    np.testing.assert_allclose(rollout.series("realized_property_gain_usd")[60], realized_gain)
    np.testing.assert_allclose(rollout.series("property_sale_capital_gain_usd")[60], realized_gain)
    np.testing.assert_allclose(rollout.series("property_sale_capital_gain_exclusion_usd")[60], 250_000)
    np.testing.assert_allclose(rollout.series("taxable_property_capital_gain_usd")[60], taxable_gain)
    np.testing.assert_allclose(rollout.series("taxable_property_gain_usd")[60], taxable_gain)
    np.testing.assert_allclose(rollout.series("property_sale_tax_usd")[60], sale_tax)
    np.testing.assert_allclose(
        rollout.series("property_sale_net_proceeds_usd")[60], sale_value - sale_closing_cost - sale_tax
    )
    np.testing.assert_allclose(
        result.matrix("net_property_sale_cash_flow_usd"), result.matrix("property_sale_net_proceeds_usd")
    )
    actions = rollout.actions(SettlePropertySaleAction)
    assert len(actions) == 1
    action = actions[0]
    assert action.event_id == "sale"
    assert action.property_id == "test_property"
    assert action.policy_id == "property_sale_settlement"
    np.testing.assert_allclose(action.gross_sale_usd, sale_value)
    np.testing.assert_allclose(action.selling_cost_usd, sale_closing_cost)
    np.testing.assert_allclose(action.debt_payoff_usd, 0)
    np.testing.assert_allclose(action.adjusted_basis_usd, 500_000)
    np.testing.assert_allclose(action.realized_gain_usd, realized_gain)
    np.testing.assert_allclose(action.capital_gain_exclusion_usd, 250_000)
    np.testing.assert_allclose(action.taxable_gain_usd, taxable_gain)
    np.testing.assert_allclose(action.tax_usd, sale_tax)
    np.testing.assert_allclose(action.net_proceeds_usd, sale_value - sale_closing_cost - sale_tax)


def test_whole_property_rental_posts_income_fees_and_cash_flow() -> None:
    """A rented property records rent, vacancy, management fee, carrying cost,
    and owner cash impact in the simulated trajectory."""
    scenario = Scenario(
        scenario_id="whole_property_rental",
        label="Whole Property Rental",
        actors=(_simple_actor(),),
        property_selection=PropertySelection(
            property_id="test_property", location_id=LocationId.VALLEJO_CA, purchase_price_usd=120_000
        ),
        financing=Financing(financing_mode=FinancingMode.CASH),
        transaction_costs=TransactionCosts(closing_cost_buy_pct=0, closing_cost_sell_pct=0),
        property_assumptions=PropertyAssumptions(insurance_annual_usd=0, maintenance_pct=0),
        rental_plan=WholePropertyRentalPlan(
            rental_mode=RentalMode.RENT_WHOLE_PROPERTY,
            start_month=1,
            monthly_rent_usd=3_000,
            vacancy_pct=5,
            management_fee_pct=8,
        ),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking",
                    account_type=AccountType.CHECKING,
                    owner_actor_id="alpha",
                    balance_usd=250_000,
                ),
            )
        ),
    )

    result = _run_scenario(scenario, horizon_months=3)

    expected_gross_rent = 3_000
    expected_vacancy_loss = expected_gross_rent * 0.05
    expected_rental_income = expected_gross_rent - expected_vacancy_loss
    expected_management_fee = expected_rental_income * 0.08
    expected_property_tax = 120_000 * 0.011 / 12
    expected_net_property_cash_flow = expected_rental_income - expected_management_fee - expected_property_tax
    rollout = result.rollout(0)
    np.testing.assert_allclose(rollout.series("rental_gross_income_usd")[0], 0)
    np.testing.assert_allclose(rollout.series("rental_gross_income_usd")[1], expected_gross_rent)
    np.testing.assert_allclose(rollout.series("rental_vacancy_loss_usd")[1], expected_vacancy_loss)
    np.testing.assert_allclose(rollout.series("rental_income_usd")[1], expected_rental_income)
    np.testing.assert_allclose(rollout.series("rental_management_fee_usd")[1], expected_management_fee)
    np.testing.assert_allclose(rollout.series("property_tax_usd")[1], expected_property_tax)
    np.testing.assert_allclose(
        rollout.series("property_carrying_cost_usd")[1], expected_management_fee + expected_property_tax
    )
    np.testing.assert_allclose(rollout.series("net_property_cash_flow_usd")[1], expected_net_property_cash_flow)
    np.testing.assert_allclose(rollout.series("cash_usd")[0], 130_000)
    np.testing.assert_allclose(rollout.series("cash_usd")[1], 130_000 + expected_net_property_cash_flow)


def test_pydantic_rejects_rental_mode_without_required_rent() -> None:
    """Rental configuration should not silently mean zero rent when rent is missing."""
    with pytest.raises(ValidationError, match=r"rental_plan\.rent_whole_property\.monthly_rent_usd"):
        Scenario.model_validate(
            {
                "scenario_id": "missing_rent",
                "label": "Missing Rent",
                "actors": [{"actor_id": "alpha", "label": "Alpha", "role": "primary_owner"}],
                "property_selection": {
                    "property_id": "test_property",
                    "location_id": "vallejo_ca",
                    "purchase_price_usd": 120_000,
                },
                "rental_plan": {"rental_mode": "rent_whole_property"},
            }
        )


def test_checking_floor_policy_sells_sp500_to_restore_cash_floor() -> None:
    """A checking-floor rule can sell SP500 after monthly spend drains cash.

    This keeps the public API focused on a distribution result while still
    making a selected rollout's action log and curves inspectable.
    """
    scenario = Scenario(
        scenario_id="checking_floor_sale",
        label="Checking Floor Sale",
        actors=(_simple_actor(),),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking", account_type=AccountType.CHECKING, owner_actor_id="alpha", balance_usd=30_000
                ),
            ),
            assets=(
                GenericSp500StockPosition(
                    asset_id="sp500",
                    asset_type=AssetType.GENERIC_SP500_STOCK,
                    owner_actor_id="alpha",
                    value_usd=50_000,
                    cost_basis_usd=25_000,
                ),
            ),
        ),
        policies=(
            MonthlySpendPolicy(policy_id="living_expenses", actor_id="alpha", monthly_spend_usd=5_000),
            CheckingFloorSellPublicStockPolicy(
                policy_id="checking_floor", actor_id="alpha", floor_usd=10_000, sale_amount_usd=20_000
            ),
        ),
    )

    result = _run_scenario(scenario, horizon_months=6)

    rollout = result.rollout(0)
    np.testing.assert_allclose(rollout.series("cash_usd"), [30_000, 25_000, 20_000, 15_000, 10_000, 25_000, 20_000])
    np.testing.assert_allclose(
        rollout.series("generic_sp500_value_usd"), [50_000, 50_000, 50_000, 50_000, 50_000, 30_000, 30_000]
    )
    np.testing.assert_allclose(rollout.series("generic_sp500_sale_usd"), [0, 0, 0, 0, 0, 20_000, 0])
    np.testing.assert_allclose(rollout.series("generic_sp500_sale_basis_usd")[5], 10_000)
    np.testing.assert_allclose(rollout.series("generic_sp500_sale_gain_usd")[5], 10_000)
    np.testing.assert_allclose(rollout.series("checking_floor_shortfall_usd"), 0)

    actions = result.actions(SellSp500Action)
    assert len(actions) == 1
    assert actions[0].month_index == 5
    assert actions[0].policy_id == "checking_floor"
    assert actions[0].amount_usd == 20_000
    assert actions[0].basis_usd == 10_000
    assert actions[0].gain_usd == 10_000
    assert actions[0].shortfall_usd == 0


def test_multiple_checking_floor_rules_execute_in_policy_order() -> None:
    """Checking-floor rules are ordered policy rules, not a singleton archetype."""
    scenario = Scenario(
        scenario_id="ordered_checking_floor_rules",
        label="Ordered Checking Floor Rules",
        actors=(_simple_actor(),),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking", account_type=AccountType.CHECKING, owner_actor_id="alpha", balance_usd=0
                ),
            ),
            assets=(
                GenericSp500StockPosition(
                    asset_id="sp500",
                    asset_type=AssetType.GENERIC_SP500_STOCK,
                    owner_actor_id="alpha",
                    value_usd=50_000,
                    cost_basis_usd=50_000,
                ),
            ),
        ),
        policies=(
            CheckingFloorSellPublicStockPolicy(
                policy_id="primary_floor", actor_id="alpha", floor_usd=10_000, sale_amount_usd=15_000
            ),
            CheckingFloorSellPublicStockPolicy(
                policy_id="top_up_floor", actor_id="alpha", floor_usd=20_000, sale_amount_usd=10_000
            ),
        ),
    )

    result = _run_scenario(scenario, horizon_months=1)

    rollout = result.rollout(0)
    np.testing.assert_allclose(rollout.series("cash_usd")[0], 25_000)
    np.testing.assert_allclose(rollout.series("generic_sp500_value_usd")[0], 25_000)
    np.testing.assert_allclose(rollout.series("generic_sp500_sale_usd")[0], 25_000)
    np.testing.assert_allclose(rollout.series("generic_sp500_sale_basis_usd")[0], 25_000)
    np.testing.assert_allclose(rollout.series("checking_floor_shortfall_usd")[0], 0)

    assert [(action.policy_id, action.amount_usd) for action in result.actions(SellSp500Action)] == [
        ("primary_floor", 15_000),
        ("top_up_floor", 10_000),
    ]


def test_private_equity_sale_request_uses_market_liquidity_opportunity() -> None:
    """A PE sale request needs both a policy decision and a market opportunity."""
    scenario = Scenario(
        scenario_id="private_equity_sale_request",
        label="Private Equity Sale Request",
        actors=(_simple_actor(),),
        events=(
            PrivateEquitySaleRequestEvent(
                event_id="sale_request", month_index=12, actor_id="alpha", amount_usd=100_000
            ),
        ),
        tax_profile=TaxProfile(cap_gains_rate=20),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking", account_type=AccountType.CHECKING, owner_actor_id="alpha", balance_usd=10_000
                ),
            ),
            assets=(
                PrivateEquityPosition(
                    asset_id="pe",
                    asset_type=AssetType.PRIVATE_EQUITY,
                    owner_actor_id="alpha",
                    value_usd=200_000,
                    cost_basis_usd=80_000,
                    units=100,
                ),
            ),
        ),
        policies=(
            PrivateEquitySalePolicy(policy_id="private_equity_sale", actor_id="alpha", proceeds_destination="cash"),
        ),
    )

    no_opportunity = _run_scenario(scenario, horizon_months=12)
    np.testing.assert_allclose(no_opportunity.rollout(0).series("private_equity_sale_usd"), 0)
    np.testing.assert_allclose(no_opportunity.rollout(0).series("cash_usd")[12], 10_000)
    assert no_opportunity.actions(SellPrivateEquityAction) == ()

    result = _run_scenario(
        scenario,
        horizon_months=12,
        market_provider=NoopMarketBundleProvider(private_equity_liquidity_event_months=(12,)),
    )

    expected_sale = 100_000
    expected_basis = 40_000
    expected_taxable_gain = 60_000
    expected_tax = 12_000
    expected_after_tax_proceeds = 88_000
    rollout = result.rollout(0)
    np.testing.assert_allclose(rollout.series("private_equity_value_usd")[11], 200_000)
    np.testing.assert_allclose(rollout.series("private_equity_sale_usd")[12], expected_sale)
    np.testing.assert_allclose(rollout.series("private_equity_sale_basis_usd")[12], expected_basis)
    np.testing.assert_allclose(rollout.series("private_equity_sale_tax_usd")[12], expected_tax)
    np.testing.assert_allclose(rollout.series("private_equity_value_usd")[12], 100_000)
    np.testing.assert_allclose(rollout.series("private_equity_liquidity_available_value_usd")[12], 100_000)
    np.testing.assert_allclose(rollout.series("cash_usd")[12], 10_000 + expected_after_tax_proceeds)
    np.testing.assert_allclose(rollout.series("net_worth_usd")[12], 10_000 + expected_after_tax_proceeds + 100_000)

    actions = result.actions(SellPrivateEquityAction)
    assert len(actions) == 1
    assert actions[0].month_index == 12
    assert actions[0].event_id == "sale_request"
    assert actions[0].actor_id == "alpha"
    assert actions[0].policy_id == "private_equity_sale"
    assert actions[0].amount_usd == expected_sale
    assert actions[0].basis_usd == expected_basis
    assert actions[0].taxable_gain_usd == expected_taxable_gain
    assert actions[0].estimated_tax_usd == expected_tax
    assert actions[0].after_tax_proceeds_usd == expected_after_tax_proceeds
    assert actions[0].units_sold == 50
    assert actions[0].sold_fraction == 0.5
    assert actions[0].proceeds_destination is AccountType.CHECKING


def test_fixed_amount_private_equity_sale_rule_sells_on_market_opportunity() -> None:
    """A PE policy can sell a configured tranche when market liquidity appears."""
    scenario = Scenario(
        scenario_id="automatic_private_equity_sale",
        label="Automatic Private Equity Sale",
        actors=(_simple_actor(),),
        tax_profile=TaxProfile(cap_gains_rate=20),
        initial_balance_sheet=InitialBalanceSheet(
            accounts=(
                AccountBalance(
                    account_id="checking", account_type=AccountType.CHECKING, owner_actor_id="alpha", balance_usd=10_000
                ),
            ),
            assets=(
                PrivateEquityPosition(
                    asset_id="pe",
                    asset_type=AssetType.PRIVATE_EQUITY,
                    owner_actor_id="alpha",
                    value_usd=200_000,
                    cost_basis_usd=80_000,
                    units=100,
                ),
            ),
        ),
        policies=(
            PrivateEquitySalePolicy(
                policy_id="private_equity_sale",
                actor_id="alpha",
                sale_rule=FixedAmountPrivateEquitySaleRule(amount_usd=50_000),
            ),
        ),
    )

    result = _run_scenario(
        scenario, horizon_months=6, market_provider=NoopMarketBundleProvider(private_equity_liquidity_event_months=(6,))
    )

    rollout = result.rollout(0)
    np.testing.assert_allclose(rollout.series("private_equity_sale_usd")[6], 50_000)
    np.testing.assert_allclose(rollout.series("private_equity_sale_basis_usd")[6], 20_000)
    np.testing.assert_allclose(rollout.series("private_equity_sale_tax_usd")[6], 6_000)
    np.testing.assert_allclose(rollout.series("private_equity_value_usd")[6], 150_000)
    np.testing.assert_allclose(rollout.series("cash_usd")[6], 54_000)
    actions = result.actions(SellPrivateEquityAction)
    assert len(actions) == 1
    assert actions[0].event_id is None
    assert actions[0].event_type is None
    assert actions[0].amount_usd == 50_000
    assert actions[0].after_tax_proceeds_usd == 44_000


def test_pydantic_rejects_private_equity_sale_request_without_amount() -> None:
    """A manual PE sale request must state its amount."""
    with pytest.raises(ValidationError, match=r"events\.0\.private_equity_sale_request\.amount_usd"):
        Scenario.model_validate(
            {
                "scenario_id": "missing_pe_sale_request_amount",
                "label": "Missing PE Sale Request Amount",
                "actors": [{"actor_id": "alpha", "label": "Alpha", "role": "primary_owner"}],
                "events": [
                    {
                        "event_id": "sale_request",
                        "event_type": "private_equity_sale_request",
                        "month_index": 12,
                        "actor_id": "alpha",
                    }
                ],
            }
        )


if __name__ == "__main__":
    pytest_bazel.main()
