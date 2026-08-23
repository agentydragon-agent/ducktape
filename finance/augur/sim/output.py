"""Dense simulator output shared by the JAX engine, codecs, and product projection."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from finance.augur.sim.tensor_types import (
    HostEventRolloutBool,
    HostLotRolloutI64,
    HostMonthPropertyRolloutBool,
    HostSnapshotCapitalGainClassRolloutBool,
    HostSnapshotCapitalGainClassRolloutI64,
    HostSnapshotCashRolloutI64,
    HostSnapshotIncomeBucketRolloutI64,
    HostSnapshotLiabilityRolloutBool,
    HostSnapshotLiabilityRolloutI64,
    HostSnapshotLotRolloutI64,
    HostSnapshotPropertyRolloutBool,
    HostSnapshotPropertyRolloutI64,
    HostSnapshotRolloutBool,
    HostSnapshotRolloutI64,
)


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
    breakdown: ArrayT
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

    cash: HostSnapshotCashRolloutI64
    ordinary: HostSnapshotIncomeBucketRolloutI64
    lots: HostSnapshotLotRolloutI64
    lot_cost_basis: HostLotRolloutI64
    lot_purchase_month: HostLotRolloutI64
    capital_gain_active: HostSnapshotCapitalGainClassRolloutBool
    capital_gain_ytd: HostSnapshotCapitalGainClassRolloutI64
    property_active: HostSnapshotPropertyRolloutBool
    property_basis: HostSnapshotPropertyRolloutI64
    property_contribution: HostSnapshotPropertyRolloutI64
    property_equity: HostSnapshotPropertyRolloutI64
    property_cumulative_depreciation: HostSnapshotPropertyRolloutI64
    property_owner_occupied_months: HostSnapshotPropertyRolloutI64
    liability_active: HostSnapshotLiabilityRolloutBool
    liability_principal: HostSnapshotLiabilityRolloutI64
    liability_monthly_payment: HostSnapshotLiabilityRolloutI64
    liability_interest_ytd: HostSnapshotLiabilityRolloutI64
    liability_principal_ytd: HostSnapshotLiabilityRolloutI64
    failed: HostSnapshotRolloutBool
    failed_month: HostSnapshotRolloutI64


class DenseSimulationOutput(NamedTuple):
    """One host-resident tree consumed directly by codecs and product projection."""

    state: DenseStateOutput
    cashflows: CashflowOutput[np.ndarray]
    obligations: ObligationOutput[np.ndarray]
    property_purchases: HostMonthPropertyRolloutBool
    mortgages: MortgageOutput[np.ndarray]
    taxes: TaxOutput[np.ndarray]
    scheduled_dispositions: DispositionOutput[np.ndarray]
    target_allocation: TargetAllocationOutput[np.ndarray]
    private_equity: PrivateEquityOutput[np.ndarray]
    lifecycle: LifecycleOutput[np.ndarray]
    primary_residence_fired: HostEventRolloutBool
