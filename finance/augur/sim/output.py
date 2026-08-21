"""Dense simulator output shared by the JAX engine, codecs, and product projection."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np


class StateOutput[ArrayT](NamedTuple):
    cash: ArrayT
    ordinary: ArrayT
    lots: ArrayT
    capital_gain_active: ArrayT
    capital_gain_ytd: ArrayT
    property_active: ArrayT
    property_basis: ArrayT
    property_contribution: ArrayT
    property_equity: ArrayT
    property_cumulative_depreciation: ArrayT
    property_owner_occupied_months: ArrayT
    liability_active: ArrayT
    liability_principal: ArrayT
    liability_monthly_payment: ArrayT
    liability_interest_ytd: ArrayT
    liability_principal_ytd: ArrayT
    failed: ArrayT
    failed_month: ArrayT


class CashflowOutput[ArrayT](NamedTuple):
    active: ArrayT
    amount: ArrayT


class ObligationOutput[ArrayT](NamedTuple):
    active: ArrayT
    due: ArrayT
    paid: ArrayT
    shortfall: ArrayT
    failure_active: ArrayT


class MortgageOutput[ArrayT](NamedTuple):
    origination_active: ArrayT
    payment_active: ArrayT
    payment_interest: ArrayT
    payment_principal: ArrayT
    payment_total: ArrayT


class TaxOutput[ArrayT](NamedTuple):
    accrual_active: ArrayT
    accrual_amount: ArrayT
    ordinary_income: ArrayT
    long_term_capital_gain: ArrayT
    short_term_capital_gain: ArrayT
    standard_deduction: ArrayT
    mortgage_interest_deduction: ArrayT
    salt_deduction: ArrayT
    itemized_deduction: ArrayT
    ordinary_taxable: ArrayT
    capital_gain_taxable: ArrayT
    ordinary_tax: ArrayT
    capital_gain_tax: ArrayT
    liability_amount: ArrayT
    liability_active: ArrayT
    settlement_active: ArrayT
    settlement_amount: ArrayT
    settlement_year_end: ArrayT


class DispositionOutput[ArrayT](NamedTuple):
    active: ArrayT
    units: ArrayT
    basis: ArrayT
    proceeds: ArrayT


class TargetAllocationOutput[ArrayT](NamedTuple):
    dispositions: DispositionOutput[ArrayT]
    obligation_attempt_policy: ArrayT


class PrivateEquityOpportunityOutput[ArrayT](NamedTuple):
    active: ArrayT
    outcome: ArrayT
    floor: ArrayT
    liquid_net_worth: ArrayT
    shortfall: ArrayT
    units_held: ArrayT
    sellable_units: ArrayT
    target_units: ArrayT
    proceeds: ArrayT


class PrivateEquityOutput[ArrayT](NamedTuple):
    dispositions: DispositionOutput[ArrayT]
    opportunities: PrivateEquityOpportunityOutput[ArrayT]


class PropertySaleTraceOutput[ArrayT](NamedTuple):
    gross_proceeds: ArrayT
    mortgage_payoff: ArrayT
    net_cash: ArrayT
    realized_gain: ArrayT
    depreciation_recapture: ArrayT
    section_121_exclusion: ArrayT
    long_term_capital_gain: ArrayT


class LifecycleOutput[ArrayT](NamedTuple):
    fired: ArrayT
    property_sales: PropertySaleTraceOutput[ArrayT]


class DenseScanOutput[ArrayT](NamedTuple):
    state: StateOutput[ArrayT]
    cashflows: CashflowOutput[ArrayT]
    obligations: ObligationOutput[ArrayT]
    property_purchases: ArrayT
    mortgages: MortgageOutput[ArrayT]
    taxes: TaxOutput[ArrayT]
    target_allocation: TargetAllocationOutput[ArrayT]
    private_equity: PrivateEquityOutput[ArrayT]
    lifecycle: LifecycleOutput[ArrayT]
    primary_residence_fired: ArrayT


class DenseFinalOutput[ArrayT](NamedTuple):
    lot_cost_basis: ArrayT
    lot_purchase_month: ArrayT
    scheduled_dispositions: DispositionOutput[ArrayT]
    sale_oversell: ArrayT
    target_allocation_buy_count: ArrayT


class DenseStateOutput(NamedTuple):
    """Host-side state history, including the month-zero snapshot."""

    cash: np.ndarray
    ordinary: np.ndarray
    lots: np.ndarray
    lot_cost_basis: np.ndarray
    lot_purchase_month: np.ndarray
    capital_gain_active: np.ndarray
    capital_gain_ytd: np.ndarray
    property_active: np.ndarray
    property_basis: np.ndarray
    property_contribution: np.ndarray
    property_equity: np.ndarray
    property_cumulative_depreciation: np.ndarray
    property_owner_occupied_months: np.ndarray
    liability_active: np.ndarray
    liability_principal: np.ndarray
    liability_monthly_payment: np.ndarray
    liability_interest_ytd: np.ndarray
    liability_principal_ytd: np.ndarray
    failed: np.ndarray
    failed_month: np.ndarray


class DenseSimulationOutput(NamedTuple):
    """One host-resident tree consumed directly by codecs and product projection."""

    state: DenseStateOutput
    cashflows: CashflowOutput[np.ndarray]
    obligations: ObligationOutput[np.ndarray]
    property_purchases: np.ndarray
    mortgages: MortgageOutput[np.ndarray]
    taxes: TaxOutput[np.ndarray]
    scheduled_dispositions: DispositionOutput[np.ndarray]
    target_allocation: TargetAllocationOutput[np.ndarray]
    private_equity: PrivateEquityOutput[np.ndarray]
    lifecycle: LifecycleOutput[np.ndarray]
    primary_residence_fired: np.ndarray
