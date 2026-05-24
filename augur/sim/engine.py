"""Dense-array simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from augur.sim.compiler import CompiledSimulation, SlotPlan, compile_simulation
from augur.sim.events import EVENT_FRAMES, EventLog
from augur.sim.external_series import ExternalSeriesContext
from augur.sim.run import SimulationRun
from augur.sim.runtime import load_jurisdictions_for, load_locations_for
from augur.sim.scenario import Scenario
from augur.sim.state import (
    ASSET_LOT_FRAME,
    CAPITAL_GAINS_YTD_FRAME,
    CASH_BALANCES_FRAME,
    LIABILITY_FRAME,
    ORDINARY_INCOME_YTD_FRAME,
    PROPERTY_STAKE_FRAME,
    PROPERTY_STATE_FRAME,
    ROLLOUT_STATUS_FRAME,
    TAX_LIABILITIES_FRAME,
)
from augur.sim.tensor_fifo import fifo_sell_dollars, fifo_sell_units, lot_order_for_pool

NO_CODE = -1
AMOUNT_FIXED = 0
LONG_TERM_CAPITAL_GAIN_CODE = 0
SHORT_TERM_CAPITAL_GAIN_CODE = 1
SOURCE_CONFIGURED_OBLIGATION = 0
SOURCE_MORTGAGE_PAYMENT = 1
SOURCE_PROPERTY_TAX = 2
SOURCE_ESTIMATED_TAX = 3
SOURCE_ESTIMATED_TAX_Q4 = 4
SOURCE_TAX_TRUE_UP = 5


def _expect_array(name: str, array: np.ndarray, *, shape: tuple[int, ...], dtype: Any) -> None:
    if array.shape != shape:
        raise ValueError(f"{name} shape {array.shape} != expected {shape}")
    if array.dtype != np.dtype(dtype):
        raise ValueError(f"{name} dtype {array.dtype} != expected {np.dtype(dtype)}")


@dataclass
class StateHistoryBuffers:
    cash_state: np.ndarray
    lot_state: np.ndarray
    ordinary_state: np.ndarray
    capital_gain_active_state: np.ndarray
    capital_gain_state: np.ndarray
    tax_liability_active_state: np.ndarray
    tax_liability_state: np.ndarray
    property_active_state: np.ndarray
    property_basis_state: np.ndarray
    property_ownership_state: np.ndarray
    property_contribution_state: np.ndarray
    property_equity_state: np.ndarray
    liability_active_state: np.ndarray
    liability_principal_state: np.ndarray
    liability_monthly_payment_state: np.ndarray
    liability_interest_ytd_state: np.ndarray
    liability_principal_ytd_state: np.ndarray
    rollout_failed_state: np.ndarray
    rollout_failed_month_state: np.ndarray

    def validate(self, plan: SlotPlan) -> None:
        s = plan.snapshot_months
        r = plan.rollout_count
        _expect_array("cash_state", self.cash_state, shape=(s, r, plan.cash_count), dtype=np.float64)
        _expect_array("lot_state", self.lot_state, shape=(s, r, plan.lot_count), dtype=np.float64)
        _expect_array("ordinary_state", self.ordinary_state, shape=(s, r, plan.tax_profile_count), dtype=np.float64)
        _expect_array(
            "capital_gain_active_state",
            self.capital_gain_active_state,
            shape=(s, r, plan.capital_gain_agent_count, 2),
            dtype=np.bool_,
        )
        _expect_array(
            "capital_gain_state",
            self.capital_gain_state,
            shape=(s, r, plan.capital_gain_agent_count, 2),
            dtype=np.float64,
        )
        _expect_array(
            "tax_liability_active_state",
            self.tax_liability_active_state,
            shape=(s, r, plan.tax_liability_count),
            dtype=np.bool_,
        )
        _expect_array(
            "tax_liability_state", self.tax_liability_state, shape=(s, r, plan.tax_liability_count), dtype=np.float64
        )
        _expect_array(
            "property_active_state", self.property_active_state, shape=(s, r, plan.property_count), dtype=np.bool_
        )
        _expect_array(
            "property_basis_state", self.property_basis_state, shape=(s, r, plan.property_count), dtype=np.float64
        )
        _expect_array(
            "property_ownership_state",
            self.property_ownership_state,
            shape=(s, r, plan.property_count),
            dtype=np.float64,
        )
        _expect_array(
            "property_contribution_state",
            self.property_contribution_state,
            shape=(s, r, plan.property_count),
            dtype=np.float64,
        )
        _expect_array(
            "property_equity_state", self.property_equity_state, shape=(s, r, plan.property_count), dtype=np.float64
        )
        _expect_array(
            "liability_active_state", self.liability_active_state, shape=(s, r, plan.liability_count), dtype=np.bool_
        )
        _expect_array(
            "liability_principal_state",
            self.liability_principal_state,
            shape=(s, r, plan.liability_count),
            dtype=np.float64,
        )
        _expect_array(
            "liability_monthly_payment_state",
            self.liability_monthly_payment_state,
            shape=(s, r, plan.liability_count),
            dtype=np.float64,
        )
        _expect_array(
            "liability_interest_ytd_state",
            self.liability_interest_ytd_state,
            shape=(s, r, plan.liability_count),
            dtype=np.float64,
        )
        _expect_array(
            "liability_principal_ytd_state",
            self.liability_principal_ytd_state,
            shape=(s, r, plan.liability_count),
            dtype=np.float64,
        )
        _expect_array("rollout_failed_state", self.rollout_failed_state, shape=(s, r), dtype=np.bool_)
        _expect_array("rollout_failed_month_state", self.rollout_failed_month_state, shape=(s, r), dtype=np.int64)


@dataclass
class CurrentStateBuffers:
    cash: np.ndarray
    lot_remaining: np.ndarray
    ordinary_ytd: np.ndarray
    capital_gain_active: np.ndarray
    capital_gain_ytd: np.ndarray
    tax_liability_active: np.ndarray
    tax_liability_amount: np.ndarray
    property_active: np.ndarray
    property_basis: np.ndarray
    property_ownership: np.ndarray
    property_contribution: np.ndarray
    property_equity: np.ndarray
    liability_active: np.ndarray
    liability_principal: np.ndarray
    liability_monthly_payment: np.ndarray
    liability_interest_ytd: np.ndarray
    liability_principal_ytd: np.ndarray
    failed: np.ndarray
    failed_month: np.ndarray

    def validate(self, plan: SlotPlan) -> None:
        r = plan.rollout_count
        _expect_array("current cash", self.cash, shape=(r, plan.cash_count), dtype=np.float64)
        _expect_array("current lot_remaining", self.lot_remaining, shape=(r, plan.lot_count), dtype=np.float64)
        _expect_array("current ordinary_ytd", self.ordinary_ytd, shape=(r, plan.tax_profile_count), dtype=np.float64)
        _expect_array(
            "current capital_gain_active",
            self.capital_gain_active,
            shape=(r, plan.capital_gain_agent_count, 2),
            dtype=np.bool_,
        )
        _expect_array(
            "current capital_gain_ytd",
            self.capital_gain_ytd,
            shape=(r, plan.capital_gain_agent_count, 2),
            dtype=np.float64,
        )
        _expect_array(
            "current tax_liability_active",
            self.tax_liability_active,
            shape=(r, plan.tax_liability_count),
            dtype=np.bool_,
        )
        _expect_array(
            "current tax_liability_amount",
            self.tax_liability_amount,
            shape=(r, plan.tax_liability_count),
            dtype=np.float64,
        )
        _expect_array("current property_active", self.property_active, shape=(r, plan.property_count), dtype=np.bool_)
        _expect_array("current property_basis", self.property_basis, shape=(r, plan.property_count), dtype=np.float64)
        _expect_array(
            "current property_ownership", self.property_ownership, shape=(r, plan.property_count), dtype=np.float64
        )
        _expect_array(
            "current property_contribution",
            self.property_contribution,
            shape=(r, plan.property_count),
            dtype=np.float64,
        )
        _expect_array("current property_equity", self.property_equity, shape=(r, plan.property_count), dtype=np.float64)
        _expect_array(
            "current liability_active", self.liability_active, shape=(r, plan.liability_count), dtype=np.bool_
        )
        _expect_array(
            "current liability_principal", self.liability_principal, shape=(r, plan.liability_count), dtype=np.float64
        )
        _expect_array(
            "current liability_monthly_payment",
            self.liability_monthly_payment,
            shape=(r, plan.liability_count),
            dtype=np.float64,
        )
        _expect_array(
            "current liability_interest_ytd",
            self.liability_interest_ytd,
            shape=(r, plan.liability_count),
            dtype=np.float64,
        )
        _expect_array(
            "current liability_principal_ytd",
            self.liability_principal_ytd,
            shape=(r, plan.liability_count),
            dtype=np.float64,
        )
        _expect_array("current failed", self.failed, shape=(r,), dtype=np.bool_)
        _expect_array("current failed_month", self.failed_month, shape=(r,), dtype=np.int64)


@dataclass
class TransferEventBuffers:
    transfer_active: np.ndarray
    transfer_amount: np.ndarray

    def validate(self, plan: SlotPlan) -> None:
        shape = (plan.event_months, plan.max_transfer_slots, plan.rollout_count)
        _expect_array("transfer_active", self.transfer_active, shape=shape, dtype=np.bool_)
        _expect_array("transfer_amount", self.transfer_amount, shape=shape, dtype=np.float64)


@dataclass
class PropertyEventBuffers:
    property_transfer_active: np.ndarray
    property_purchase_active: np.ndarray
    mortgage_origination_active: np.ndarray
    mortgage_payment_active: np.ndarray
    mortgage_payment_interest: np.ndarray
    mortgage_payment_principal: np.ndarray
    mortgage_payment_total: np.ndarray

    def validate(self, plan: SlotPlan) -> None:
        h = plan.event_months
        r = plan.rollout_count
        property_shape = (h, plan.property_count, r)
        liability_event_shape = (h, max(1, plan.liability_count), r)
        _expect_array("property_transfer_active", self.property_transfer_active, shape=property_shape, dtype=np.bool_)
        _expect_array("property_purchase_active", self.property_purchase_active, shape=property_shape, dtype=np.bool_)
        _expect_array(
            "mortgage_origination_active", self.mortgage_origination_active, shape=liability_event_shape, dtype=np.bool_
        )
        _expect_array(
            "mortgage_payment_active", self.mortgage_payment_active, shape=liability_event_shape, dtype=np.bool_
        )
        _expect_array(
            "mortgage_payment_interest", self.mortgage_payment_interest, shape=liability_event_shape, dtype=np.float64
        )
        _expect_array(
            "mortgage_payment_principal", self.mortgage_payment_principal, shape=liability_event_shape, dtype=np.float64
        )
        _expect_array(
            "mortgage_payment_total", self.mortgage_payment_total, shape=liability_event_shape, dtype=np.float64
        )


@dataclass
class LotDispositionEventBuffers:
    sched_disp_active: np.ndarray
    sched_disp_units: np.ndarray
    sched_disp_basis: np.ndarray
    sched_disp_proceeds: np.ndarray
    liq_disp_active: np.ndarray
    liq_disp_units: np.ndarray
    liq_disp_basis: np.ndarray
    liq_disp_proceeds: np.ndarray

    def validate(self, plan: SlotPlan) -> None:
        h = plan.event_months
        r = plan.rollout_count
        lot_axis = max(1, plan.lot_count)
        scheduled_shape = (h, plan.scheduled_sale_count, lot_axis, r)
        liquidity_shape = (h, plan.liquidity_policy_count, plan.max_liquidity_policy_assets, lot_axis, r)
        _expect_array("sched_disp_active", self.sched_disp_active, shape=scheduled_shape, dtype=np.bool_)
        _expect_array("sched_disp_units", self.sched_disp_units, shape=scheduled_shape, dtype=np.float64)
        _expect_array("sched_disp_basis", self.sched_disp_basis, shape=scheduled_shape, dtype=np.float64)
        _expect_array("sched_disp_proceeds", self.sched_disp_proceeds, shape=scheduled_shape, dtype=np.float64)
        _expect_array("liq_disp_active", self.liq_disp_active, shape=liquidity_shape, dtype=np.bool_)
        _expect_array("liq_disp_units", self.liq_disp_units, shape=liquidity_shape, dtype=np.float64)
        _expect_array("liq_disp_basis", self.liq_disp_basis, shape=liquidity_shape, dtype=np.float64)
        _expect_array("liq_disp_proceeds", self.liq_disp_proceeds, shape=liquidity_shape, dtype=np.float64)


@dataclass
class TaxEventBuffers:
    tax_accrual_active: np.ndarray
    tax_accrual_amount: np.ndarray
    tax_breakdown_ordinary: np.ndarray
    tax_breakdown_ltcg: np.ndarray
    tax_breakdown_stcg: np.ndarray
    tax_breakdown_standard_deduction: np.ndarray
    tax_breakdown_mortgage_interest_deduction: np.ndarray
    tax_breakdown_itemized_deduction: np.ndarray
    tax_breakdown_ordinary_taxable: np.ndarray
    tax_breakdown_capital_taxable: np.ndarray
    tax_breakdown_ordinary_tax: np.ndarray
    tax_breakdown_capital_tax: np.ndarray
    tax_settlement_active: np.ndarray
    tax_settlement_amount: np.ndarray
    tax_settlement_year_end_month: np.ndarray

    def validate(self, plan: SlotPlan) -> None:
        h = plan.event_months
        r = plan.rollout_count
        tax_link_shape = (h, plan.tax_link_count, r)
        tax_settlement_shape = (h, plan.max_tax_settlement_slots, r)
        _expect_array("tax_accrual_active", self.tax_accrual_active, shape=tax_link_shape, dtype=np.bool_)
        _expect_array("tax_accrual_amount", self.tax_accrual_amount, shape=tax_link_shape, dtype=np.float64)
        _expect_array("tax_breakdown_ordinary", self.tax_breakdown_ordinary, shape=tax_link_shape, dtype=np.float64)
        _expect_array("tax_breakdown_ltcg", self.tax_breakdown_ltcg, shape=tax_link_shape, dtype=np.float64)
        _expect_array("tax_breakdown_stcg", self.tax_breakdown_stcg, shape=tax_link_shape, dtype=np.float64)
        _expect_array(
            "tax_breakdown_standard_deduction",
            self.tax_breakdown_standard_deduction,
            shape=tax_link_shape,
            dtype=np.float64,
        )
        _expect_array(
            "tax_breakdown_mortgage_interest_deduction",
            self.tax_breakdown_mortgage_interest_deduction,
            shape=tax_link_shape,
            dtype=np.float64,
        )
        _expect_array(
            "tax_breakdown_itemized_deduction",
            self.tax_breakdown_itemized_deduction,
            shape=tax_link_shape,
            dtype=np.float64,
        )
        _expect_array(
            "tax_breakdown_ordinary_taxable",
            self.tax_breakdown_ordinary_taxable,
            shape=tax_link_shape,
            dtype=np.float64,
        )
        _expect_array(
            "tax_breakdown_capital_taxable", self.tax_breakdown_capital_taxable, shape=tax_link_shape, dtype=np.float64
        )
        _expect_array(
            "tax_breakdown_ordinary_tax", self.tax_breakdown_ordinary_tax, shape=tax_link_shape, dtype=np.float64
        )
        _expect_array(
            "tax_breakdown_capital_tax", self.tax_breakdown_capital_tax, shape=tax_link_shape, dtype=np.float64
        )
        _expect_array("tax_settlement_active", self.tax_settlement_active, shape=tax_settlement_shape, dtype=np.bool_)
        _expect_array("tax_settlement_amount", self.tax_settlement_amount, shape=tax_settlement_shape, dtype=np.float64)
        _expect_array(
            "tax_settlement_year_end_month",
            self.tax_settlement_year_end_month,
            shape=tax_settlement_shape,
            dtype=np.int64,
        )


@dataclass
class ObligationEventBuffers:
    obligation_active: np.ndarray
    obligation_due: np.ndarray
    obligation_paid: np.ndarray
    obligation_shortfall: np.ndarray
    obligation_attempt_policy: np.ndarray
    obligation_failure_active: np.ndarray

    def validate(self, plan: SlotPlan) -> None:
        shape = (plan.event_months, plan.max_obligation_slots, plan.rollout_count)
        _expect_array("obligation_active", self.obligation_active, shape=shape, dtype=np.bool_)
        _expect_array("obligation_due", self.obligation_due, shape=shape, dtype=np.float64)
        _expect_array("obligation_paid", self.obligation_paid, shape=shape, dtype=np.float64)
        _expect_array("obligation_shortfall", self.obligation_shortfall, shape=shape, dtype=np.float64)
        _expect_array("obligation_attempt_policy", self.obligation_attempt_policy, shape=shape, dtype=np.int64)
        _expect_array("obligation_failure_active", self.obligation_failure_active, shape=shape, dtype=np.bool_)


@dataclass
class SimulationBuffers:
    state: StateHistoryBuffers
    transfers: TransferEventBuffers
    properties: PropertyEventBuffers
    lot_dispositions: LotDispositionEventBuffers
    taxes: TaxEventBuffers
    obligations: ObligationEventBuffers

    def validate(self, plan: CompiledSimulation) -> None:
        slot_plan = plan.slot_plan
        if slot_plan.event_months != plan.horizon_months:
            raise ValueError("slot plan event months do not match compiled horizon")
        if slot_plan.rollout_count != plan.rollout_count:
            raise ValueError("slot plan rollout count does not match compiled rollout count")
        self.state.validate(slot_plan)
        self.transfers.validate(slot_plan)
        self.properties.validate(slot_plan)
        self.lot_dispositions.validate(slot_plan)
        self.taxes.validate(slot_plan)
        self.obligations.validate(slot_plan)

    @property
    def cash_state(self) -> np.ndarray:
        return self.state.cash_state

    @property
    def lot_state(self) -> np.ndarray:
        return self.state.lot_state

    @property
    def ordinary_state(self) -> np.ndarray:
        return self.state.ordinary_state

    @property
    def capital_gain_active_state(self) -> np.ndarray:
        return self.state.capital_gain_active_state

    @property
    def capital_gain_state(self) -> np.ndarray:
        return self.state.capital_gain_state

    @property
    def tax_liability_active_state(self) -> np.ndarray:
        return self.state.tax_liability_active_state

    @property
    def tax_liability_state(self) -> np.ndarray:
        return self.state.tax_liability_state

    @property
    def property_active_state(self) -> np.ndarray:
        return self.state.property_active_state

    @property
    def property_basis_state(self) -> np.ndarray:
        return self.state.property_basis_state

    @property
    def property_ownership_state(self) -> np.ndarray:
        return self.state.property_ownership_state

    @property
    def property_contribution_state(self) -> np.ndarray:
        return self.state.property_contribution_state

    @property
    def property_equity_state(self) -> np.ndarray:
        return self.state.property_equity_state

    @property
    def liability_active_state(self) -> np.ndarray:
        return self.state.liability_active_state

    @property
    def liability_principal_state(self) -> np.ndarray:
        return self.state.liability_principal_state

    @property
    def liability_monthly_payment_state(self) -> np.ndarray:
        return self.state.liability_monthly_payment_state

    @property
    def liability_interest_ytd_state(self) -> np.ndarray:
        return self.state.liability_interest_ytd_state

    @property
    def liability_principal_ytd_state(self) -> np.ndarray:
        return self.state.liability_principal_ytd_state

    @property
    def rollout_failed_state(self) -> np.ndarray:
        return self.state.rollout_failed_state

    @property
    def rollout_failed_month_state(self) -> np.ndarray:
        return self.state.rollout_failed_month_state

    @property
    def transfer_active(self) -> np.ndarray:
        return self.transfers.transfer_active

    @property
    def transfer_amount(self) -> np.ndarray:
        return self.transfers.transfer_amount

    @property
    def property_transfer_active(self) -> np.ndarray:
        return self.properties.property_transfer_active

    @property
    def property_purchase_active(self) -> np.ndarray:
        return self.properties.property_purchase_active

    @property
    def mortgage_origination_active(self) -> np.ndarray:
        return self.properties.mortgage_origination_active

    @property
    def mortgage_payment_active(self) -> np.ndarray:
        return self.properties.mortgage_payment_active

    @property
    def mortgage_payment_interest(self) -> np.ndarray:
        return self.properties.mortgage_payment_interest

    @property
    def mortgage_payment_principal(self) -> np.ndarray:
        return self.properties.mortgage_payment_principal

    @property
    def mortgage_payment_total(self) -> np.ndarray:
        return self.properties.mortgage_payment_total

    @property
    def sched_disp_active(self) -> np.ndarray:
        return self.lot_dispositions.sched_disp_active

    @property
    def sched_disp_units(self) -> np.ndarray:
        return self.lot_dispositions.sched_disp_units

    @property
    def sched_disp_basis(self) -> np.ndarray:
        return self.lot_dispositions.sched_disp_basis

    @property
    def sched_disp_proceeds(self) -> np.ndarray:
        return self.lot_dispositions.sched_disp_proceeds

    @property
    def liq_disp_active(self) -> np.ndarray:
        return self.lot_dispositions.liq_disp_active

    @property
    def liq_disp_units(self) -> np.ndarray:
        return self.lot_dispositions.liq_disp_units

    @property
    def liq_disp_basis(self) -> np.ndarray:
        return self.lot_dispositions.liq_disp_basis

    @property
    def liq_disp_proceeds(self) -> np.ndarray:
        return self.lot_dispositions.liq_disp_proceeds

    @property
    def tax_accrual_active(self) -> np.ndarray:
        return self.taxes.tax_accrual_active

    @property
    def tax_accrual_amount(self) -> np.ndarray:
        return self.taxes.tax_accrual_amount

    @property
    def tax_breakdown_ordinary(self) -> np.ndarray:
        return self.taxes.tax_breakdown_ordinary

    @property
    def tax_breakdown_ltcg(self) -> np.ndarray:
        return self.taxes.tax_breakdown_ltcg

    @property
    def tax_breakdown_stcg(self) -> np.ndarray:
        return self.taxes.tax_breakdown_stcg

    @property
    def tax_breakdown_standard_deduction(self) -> np.ndarray:
        return self.taxes.tax_breakdown_standard_deduction

    @property
    def tax_breakdown_mortgage_interest_deduction(self) -> np.ndarray:
        return self.taxes.tax_breakdown_mortgage_interest_deduction

    @property
    def tax_breakdown_itemized_deduction(self) -> np.ndarray:
        return self.taxes.tax_breakdown_itemized_deduction

    @property
    def tax_breakdown_ordinary_taxable(self) -> np.ndarray:
        return self.taxes.tax_breakdown_ordinary_taxable

    @property
    def tax_breakdown_capital_taxable(self) -> np.ndarray:
        return self.taxes.tax_breakdown_capital_taxable

    @property
    def tax_breakdown_ordinary_tax(self) -> np.ndarray:
        return self.taxes.tax_breakdown_ordinary_tax

    @property
    def tax_breakdown_capital_tax(self) -> np.ndarray:
        return self.taxes.tax_breakdown_capital_tax

    @property
    def tax_settlement_active(self) -> np.ndarray:
        return self.taxes.tax_settlement_active

    @property
    def tax_settlement_amount(self) -> np.ndarray:
        return self.taxes.tax_settlement_amount

    @property
    def tax_settlement_year_end_month(self) -> np.ndarray:
        return self.taxes.tax_settlement_year_end_month

    @property
    def obligation_active(self) -> np.ndarray:
        return self.obligations.obligation_active

    @property
    def obligation_due(self) -> np.ndarray:
        return self.obligations.obligation_due

    @property
    def obligation_paid(self) -> np.ndarray:
        return self.obligations.obligation_paid

    @property
    def obligation_shortfall(self) -> np.ndarray:
        return self.obligations.obligation_shortfall

    @property
    def obligation_attempt_policy(self) -> np.ndarray:
        return self.obligations.obligation_attempt_policy

    @property
    def obligation_failure_active(self) -> np.ndarray:
        return self.obligations.obligation_failure_active


@dataclass
class DenseSimulationResult:
    plan: CompiledSimulation
    buffers: SimulationBuffers
    external_series: ExternalSeriesContext

    def decode(self) -> SimulationRun:
        return _decode_run(self.plan, self.buffers, self.external_series)


def simulate_with_external_series_dense(
    scenario: Scenario, *, rollout_count: int, external_series: ExternalSeriesContext
) -> SimulationRun:
    return simulate_with_external_series_dense_result(
        scenario, rollout_count=rollout_count, external_series=external_series
    ).decode()


def simulate_with_external_series_dense_result(
    scenario: Scenario, *, rollout_count: int, external_series: ExternalSeriesContext
) -> DenseSimulationResult:
    plan = compile_simulation(
        scenario,
        rollout_count=rollout_count,
        external_series=external_series,
        jurisdictions=load_jurisdictions_for(scenario),
        locations=load_locations_for(scenario),
    )
    buffers = _allocate_buffers(plan)
    current = _allocate_current_state(plan)
    _snapshot_initial_state(buffers, current)
    for month in range(plan.horizon_months):
        _run_month_step(plan, buffers, current, month)
    return DenseSimulationResult(plan=plan, buffers=buffers, external_series=external_series)


def _allocate_current_state(plan: CompiledSimulation) -> CurrentStateBuffers:
    p = plan.slot_plan
    r = p.rollout_count
    current = CurrentStateBuffers(
        cash=np.broadcast_to(plan.cash_initial_balance, (r, p.cash_count)).copy(),
        lot_remaining=np.broadcast_to(plan.lot_initial_quantity, (r, p.lot_count)).copy(),
        ordinary_ytd=np.zeros((r, p.tax_profile_count), dtype=np.float64),
        capital_gain_active=np.zeros((r, p.capital_gain_agent_count, 2), dtype=np.bool_),
        capital_gain_ytd=np.zeros((r, p.capital_gain_agent_count, 2), dtype=np.float64),
        tax_liability_active=np.zeros((r, p.tax_liability_count), dtype=np.bool_),
        tax_liability_amount=np.zeros((r, p.tax_liability_count), dtype=np.float64),
        property_active=np.zeros((r, p.property_count), dtype=np.bool_),
        property_basis=np.zeros((r, p.property_count), dtype=np.float64),
        property_ownership=np.zeros((r, p.property_count), dtype=np.float64),
        property_contribution=np.zeros((r, p.property_count), dtype=np.float64),
        property_equity=np.zeros((r, p.property_count), dtype=np.float64),
        liability_active=np.zeros((r, p.liability_count), dtype=np.bool_),
        liability_principal=np.zeros((r, p.liability_count), dtype=np.float64),
        liability_monthly_payment=np.zeros((r, p.liability_count), dtype=np.float64),
        liability_interest_ytd=np.zeros((r, p.liability_count), dtype=np.float64),
        liability_principal_ytd=np.zeros((r, p.liability_count), dtype=np.float64),
        failed=np.zeros(r, dtype=np.bool_),
        failed_month=np.full(r, NO_CODE, dtype=np.int64),
    )
    current.validate(p)
    return current


def _snapshot_initial_state(buffers: SimulationBuffers, current: CurrentStateBuffers) -> None:
    _snapshot_current_state(buffers, current, snapshot_index=0)


def _snapshot_current_state(buffers: SimulationBuffers, current: CurrentStateBuffers, *, snapshot_index: int) -> None:
    buffers.cash_state[snapshot_index] = current.cash
    buffers.lot_state[snapshot_index] = current.lot_remaining
    buffers.ordinary_state[snapshot_index] = current.ordinary_ytd
    buffers.capital_gain_active_state[snapshot_index] = current.capital_gain_active
    buffers.capital_gain_state[snapshot_index] = current.capital_gain_ytd
    buffers.tax_liability_active_state[snapshot_index] = current.tax_liability_active
    buffers.tax_liability_state[snapshot_index] = current.tax_liability_amount
    buffers.property_active_state[snapshot_index] = current.property_active
    buffers.property_basis_state[snapshot_index] = current.property_basis
    buffers.property_ownership_state[snapshot_index] = current.property_ownership
    buffers.property_contribution_state[snapshot_index] = current.property_contribution
    buffers.property_equity_state[snapshot_index] = current.property_equity
    buffers.liability_active_state[snapshot_index] = current.liability_active
    buffers.liability_principal_state[snapshot_index] = current.liability_principal
    buffers.liability_monthly_payment_state[snapshot_index] = current.liability_monthly_payment
    buffers.liability_interest_ytd_state[snapshot_index] = current.liability_interest_ytd
    buffers.liability_principal_ytd_state[snapshot_index] = current.liability_principal_ytd
    buffers.rollout_failed_state[snapshot_index] = current.failed
    buffers.rollout_failed_month_state[snapshot_index] = current.failed_month


def _zero_failed_state(current: CurrentStateBuffers) -> None:
    failed = current.failed
    if not failed.any():
        return
    current.cash[failed] = 0.0
    current.lot_remaining[failed] = 0.0
    current.ordinary_ytd[failed] = 0.0
    current.capital_gain_ytd[failed] = 0.0
    current.tax_liability_amount[failed] = 0.0
    current.property_basis[failed] = 0.0
    current.property_ownership[failed] = 0.0
    current.property_contribution[failed] = 0.0
    current.property_equity[failed] = 0.0
    current.liability_principal[failed] = 0.0
    current.liability_monthly_payment[failed] = 0.0
    current.liability_interest_ytd[failed] = 0.0
    current.liability_principal_ytd[failed] = 0.0


def _run_month_step(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    _apply_scheduled_transfers(plan, buffers, current, month)
    _apply_property_purchases(plan, buffers, current, month)
    _apply_scheduled_asset_sales(plan, buffers, current, month)
    _apply_obligation_accruals(plan, buffers, current, month)
    _apply_liquidity_policy_sales(plan, buffers, current, month)
    _apply_obligation_settlement(plan, buffers, current, month)
    # Tax accruals run last so December's mortgage payment has already landed its interest into
    # `liability_interest_ytd` before the year-end MID computation reads it.
    _apply_tax_accruals(plan, buffers, current, month)
    _zero_failed_state(current)
    _snapshot_current_state(buffers, current, snapshot_index=month + 1)


def _apply_scheduled_transfers(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for slot in range(plan.transfer_cause_codes.shape[1]):
        if plan.transfer_cause_codes[month, slot] < 0:
            continue
        amount = _amount_values(
            plan,
            kind=int(plan.transfer_amount_kind[month, slot]),
            fixed=float(plan.transfer_amount_fixed[month, slot]),
            base=float(plan.transfer_amount_base[month, slot]),
            series_index=int(plan.transfer_amount_series_index[month, slot]),
            base_month=int(plan.transfer_amount_base_month[month, slot]),
            adjustment_period=int(plan.transfer_amount_adjustment_period[month, slot]),
            month=month,
        )
        buffers.transfer_active[month, slot, active_rollout] = True
        buffers.transfer_amount[month, slot, active_rollout] = amount[active_rollout]
        from_slot = int(plan.transfer_from_cash_slot[month, slot])
        if from_slot >= 0:
            current.cash[active_rollout, from_slot] -= amount[active_rollout]
        to_slot = int(plan.transfer_to_cash_slot[month, slot])
        if to_slot >= 0:
            current.cash[active_rollout, to_slot] += amount[active_rollout]
        profile = int(plan.transfer_income_profile_index[month, slot])
        if profile >= 0:
            current.ordinary_ytd[active_rollout, profile] += amount[active_rollout]


def _amount_values(
    plan: CompiledSimulation,
    *,
    kind: int,
    fixed: float,
    base: float,
    series_index: int,
    base_month: int,
    adjustment_period: int,
    month: int,
) -> np.ndarray:
    if kind == AMOUNT_FIXED:
        return np.full(plan.rollout_count, fixed, dtype=np.float64)
    elapsed = month - base_month
    reset_month = base_month + (elapsed // adjustment_period) * adjustment_period
    base_level = plan.external_values[series_index, :, base_month]
    reset_level = plan.external_values[series_index, :, reset_month]
    return base * reset_level / base_level


def _apply_tax_accruals(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if month % 12 != 11 or not active_rollout.any():
        return

    for link in range(plan.tax_link_profile_index.shape[0]):
        profile = int(plan.tax_link_profile_index[link])
        gain_profile = int(plan.tax_profile_capital_gain_index[profile])
        ordinary = current.ordinary_ytd[:, profile]
        ltcg = current.capital_gain_ytd[:, gain_profile, LONG_TERM_CAPITAL_GAIN_CODE]
        stcg = current.capital_gain_ytd[:, gain_profile, SHORT_TERM_CAPITAL_GAIN_CODE]
        standard_deduction = float(plan.tax_link_standard_deduction[link])
        if bool(plan.tax_link_mid_active[link]):
            # interest_ytd: (rollouts, L); ratio: (L,) — matmul gives (rollouts,)
            mortgage_interest_deduction = current.liability_interest_ytd @ plan.tax_link_mid_principal_ratio[link]
        else:
            mortgage_interest_deduction = np.zeros(plan.rollout_count, dtype=np.float64)
        # Today the only itemized line is MID. Once SALT / state-tax / charitable arrive, sum them
        # here. The taxpayer uses max(itemized, standard); we expose both so the consumer can
        # tell which one drove the tax bill.
        itemized_deduction = mortgage_interest_deduction
        deduction_used = np.maximum(itemized_deduction, standard_deduction)

        if int(plan.tax_link_has_ltcg[link]) == 1:
            ordinary_taxable = np.maximum(ordinary + stcg - deduction_used, 0.0)
            capital_taxable = ltcg
            ordinary_tax = _apply_brackets(
                ordinary_taxable,
                upper=plan.tax_link_ordinary_upper[link],
                rate=plan.tax_link_ordinary_rate[link],
                count=int(plan.tax_link_ordinary_count[link]),
            )
            capital_tax = _apply_ltcg_brackets(
                ltcg,
                ordinary_taxable,
                upper=plan.tax_link_ltcg_upper[link],
                rate=plan.tax_link_ltcg_rate[link],
                count=int(plan.tax_link_ltcg_count[link]),
            )
        else:
            ordinary_taxable = np.maximum(ordinary + ltcg + stcg - deduction_used, 0.0)
            capital_taxable = np.zeros(plan.rollout_count, dtype=np.float64)
            ordinary_tax = _apply_brackets(
                ordinary_taxable,
                upper=plan.tax_link_ordinary_upper[link],
                rate=plan.tax_link_ordinary_rate[link],
                count=int(plan.tax_link_ordinary_count[link]),
            )
            capital_tax = np.zeros(plan.rollout_count, dtype=np.float64)

        tax = ordinary_tax + capital_tax
        buffers.tax_accrual_active[month, link, active_rollout] = True
        buffers.tax_accrual_amount[month, link, active_rollout] = tax[active_rollout]
        buffers.tax_breakdown_ordinary[month, link, active_rollout] = ordinary[active_rollout]
        buffers.tax_breakdown_ltcg[month, link, active_rollout] = ltcg[active_rollout]
        buffers.tax_breakdown_stcg[month, link, active_rollout] = stcg[active_rollout]
        buffers.tax_breakdown_standard_deduction[month, link, active_rollout] = standard_deduction
        buffers.tax_breakdown_mortgage_interest_deduction[month, link, active_rollout] = mortgage_interest_deduction[
            active_rollout
        ]
        buffers.tax_breakdown_itemized_deduction[month, link, active_rollout] = itemized_deduction[active_rollout]
        buffers.tax_breakdown_ordinary_taxable[month, link, active_rollout] = ordinary_taxable[active_rollout]
        buffers.tax_breakdown_capital_taxable[month, link, active_rollout] = capital_taxable[active_rollout]
        buffers.tax_breakdown_ordinary_tax[month, link, active_rollout] = ordinary_tax[active_rollout]
        buffers.tax_breakdown_capital_tax[month, link, active_rollout] = capital_tax[active_rollout]

        tax_slot = _tax_liability_slot_for(plan, profile_index=profile, link_index=link, year_end_month=month)
        if tax_slot >= 0:
            current.tax_liability_active[active_rollout, tax_slot] = True
            current.tax_liability_amount[active_rollout, tax_slot] = tax[active_rollout]

    for profile in range(current.ordinary_ytd.shape[1]):
        current.ordinary_ytd[active_rollout, profile] = 0.0
        gain_profile = int(plan.tax_profile_capital_gain_index[profile])
        ltcg_active = active_rollout & current.capital_gain_active[:, gain_profile, LONG_TERM_CAPITAL_GAIN_CODE]
        stcg_active = active_rollout & current.capital_gain_active[:, gain_profile, SHORT_TERM_CAPITAL_GAIN_CODE]
        current.capital_gain_ytd[ltcg_active, gain_profile, LONG_TERM_CAPITAL_GAIN_CODE] = 0.0
        current.capital_gain_ytd[stcg_active, gain_profile, SHORT_TERM_CAPITAL_GAIN_CODE] = 0.0
    # Zero YTD interest at year-end so next year's MID accumulation starts fresh. Mirrors the
    # ordinary/capital-gain YTD resets above.
    current.liability_interest_ytd[active_rollout, :] = 0.0


def _apply_brackets(amount: np.ndarray, *, upper: np.ndarray, rate: np.ndarray, count: int) -> np.ndarray:
    if count <= 0:
        return np.zeros(amount.shape, dtype=np.float64)
    upper = upper[:count]
    rate = rate[:count]
    previous_upper = np.concatenate((np.array([0.0], dtype=np.float64), upper[:-1]))
    slice_top = np.minimum(amount[:, None], upper[None, :])
    in_bracket = np.maximum(slice_top - previous_upper[None, :], 0.0)
    return (in_bracket * rate[None, :]).sum(axis=1)


def _apply_ltcg_brackets(
    ltcg_amount: np.ndarray, ordinary_taxable: np.ndarray, *, upper: np.ndarray, rate: np.ndarray, count: int
) -> np.ndarray:
    if count <= 0:
        return np.zeros(ltcg_amount.shape, dtype=np.float64)
    upper = upper[:count]
    rate = rate[:count]
    previous_upper = np.concatenate((np.array([0.0], dtype=np.float64), upper[:-1]))
    total_taxable = ordinary_taxable + ltcg_amount
    slice_top = np.minimum(total_taxable[:, None], upper[None, :])
    slice_bottom = np.maximum(ordinary_taxable[:, None], previous_upper[None, :])
    in_bracket = np.maximum(slice_top - slice_bottom, 0.0)
    return (in_bracket * rate[None, :]).sum(axis=1)


def _tax_liability_slot_for(
    plan: CompiledSimulation, *, profile_index: int, link_index: int, year_end_month: int
) -> int:
    slots = np.flatnonzero(
        (plan.tax_liability_profile_index == profile_index)
        & (plan.tax_liability_link_index == link_index)
        & (plan.tax_liability_year_end_month == year_end_month)
    )
    if slots.size == 0:
        return NO_CODE
    return int(slots[0])


def _apply_property_purchases(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for prop in range(plan.property_month.shape[0]):
        if plan.property_month[prop] != month:
            continue
        buffers.property_purchase_active[month, prop, active_rollout] = True
        current.property_active[active_rollout, prop] = True
        current.property_basis[active_rollout, prop] = plan.property_adjusted_basis[prop]
        current.property_ownership[active_rollout, prop] = plan.property_ownership_pct[prop]
        current.property_contribution[active_rollout, prop] = plan.property_stake_contribution[prop]
        current.property_equity[active_rollout, prop] = plan.property_equity_ledger[prop]

        buyer_cash = float(plan.property_stake_contribution[prop])
        if buyer_cash > 0.0:
            buffers.property_transfer_active[month, prop, active_rollout] = True
            buyer_slot = int(plan.property_buyer_cash_slot[prop])
            if buyer_slot >= 0:
                current.cash[active_rollout, buyer_slot] -= buyer_cash
            seller_slot = int(plan.property_seller_cash_slot[prop])
            if seller_slot >= 0:
                current.cash[active_rollout, seller_slot] += buyer_cash

        liability_slot = int(plan.property_mortgage_slot[prop])
        if liability_slot >= 0:
            buffers.mortgage_origination_active[month, liability_slot, active_rollout] = True
            current.liability_active[active_rollout, liability_slot] = True
            current.liability_principal[active_rollout, liability_slot] = plan.liability_principal[liability_slot]
            current.liability_monthly_payment[active_rollout, liability_slot] = plan.liability_monthly_payment[
                liability_slot
            ]
            current.liability_interest_ytd[active_rollout, liability_slot] = 0.0
            current.liability_principal_ytd[active_rollout, liability_slot] = 0.0


def _apply_scheduled_asset_sales(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for sale in range(plan.sale_month.shape[0]):
        if plan.sale_month[sale] != month:
            continue
        ordered_lots = lot_order_for_pool(
            lot_agent_codes=plan.lot_agent_codes,
            lot_account_codes=plan.lot_account_codes,
            lot_asset_codes=plan.lot_asset_codes,
            lot_purchase_month=plan.lot_purchase_month,
            lot_id_codes=plan.lot_id_codes,
            agent_code=int(plan.sale_agent_codes[sale]),
            account_code=int(plan.sale_source_account_codes[sale]),
            asset_code=int(plan.sale_asset_codes[sale]),
        )
        target_units = np.where(active_rollout, float(plan.sale_quantity[sale]), 0.0)
        price = _sale_unit_price(plan, month=month, sale=sale)
        result = fifo_sell_units(
            lot_remaining=current.lot_remaining,
            ordered_lots=ordered_lots,
            target_units=target_units,
            unit_price=price,
            cost_basis_per_unit=plan.lot_cost_basis_per_unit,
        )
        if result.oversell.any():
            raise ValueError(
                f"scheduled asset sale exceeds available lots: {_text(plan, plan.sale_cause_codes[month, sale])}"
            )

        current.lot_remaining -= result.sold_units
        proceeds_slot = int(plan.sale_proceeds_cash_slot[sale])
        if proceeds_slot >= 0:
            current.cash[:, proceeds_slot] += result.total_proceeds
        _record_capital_gains(
            plan,
            current,
            month=month,
            agent_code=int(plan.sale_agent_codes[sale]),
            sold_units=result.sold_units,
            gains=result.proceeds - result.cost_basis_consumed,
        )
        sale_active = result.sold_units > 0.0
        buffers.sched_disp_active[month, sale] = sale_active.T
        buffers.sched_disp_units[month, sale] += result.sold_units.T
        buffers.sched_disp_basis[month, sale] += result.cost_basis_consumed.T
        buffers.sched_disp_proceeds[month, sale] += result.proceeds.T


def _apply_liquidity_policy_sales(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if not active_rollout.any():
        return

    obligation_active = buffers.obligation_active[month]
    obligation_due = buffers.obligation_due[month]
    for policy in range(plan.liquidity_policy_agent_codes.shape[0]):
        policy_agent = int(plan.liquidity_policy_agent_codes[policy])
        policy_account = int(plan.liquidity_policy_account_codes[policy])
        policy_cash_slot = int(plan.liquidity_policy_cash_slot[policy])

        matching_obligations = np.flatnonzero(
            (plan.obligation_agent_codes[month] == policy_agent)
            & (plan.obligation_from_cash_slot[month] == policy_cash_slot)
        )
        if matching_obligations.size:
            matching_active = obligation_active[matching_obligations]
            hard_demand = np.where(matching_active, obligation_due[matching_obligations], 0.0).sum(axis=0)
            for row, slot in enumerate(matching_obligations):
                buffers.obligation_attempt_policy[month, slot, matching_active[row]] = policy
        else:
            hard_demand = np.zeros(plan.rollout_count, dtype=np.float64)

        cash_balance = (
            current.cash[:, policy_cash_slot]
            if policy_cash_slot >= 0
            else np.zeros(plan.rollout_count, dtype=np.float64)
        )
        required_sale = np.maximum(hard_demand - cash_balance, 0.0)
        post_required_cash = cash_balance + required_sale - hard_demand
        buffer_sale = np.where(
            (float(plan.liquidity_policy_buffer_sale[policy]) > 0.0)
            & (post_required_cash < float(plan.liquidity_policy_buffer_trigger[policy])),
            float(plan.liquidity_policy_buffer_sale[policy]),
            0.0,
        )
        remaining_target = np.where(active_rollout, required_sale + buffer_sale, 0.0)
        if not np.any((hard_demand > 0.0) | (remaining_target > 0.0)):
            continue

        for asset_idx in range(plan.liquidity_policy_asset_codes.shape[1]):
            asset_code = int(plan.liquidity_policy_asset_codes[policy, asset_idx])
            if asset_code < 0 or not np.any(remaining_target > 0.0):
                continue
            series_index = int(plan.liquidity_policy_asset_series_index[policy, asset_idx])
            if series_index < 0:
                continue
            raw_price = plan.external_values[series_index, :, month]
            valid_price = np.isfinite(raw_price) & (raw_price > 0.0)
            unit_price = np.where(valid_price, raw_price, 0.0)

            ordered_lots = lot_order_for_pool(
                lot_agent_codes=plan.lot_agent_codes,
                lot_account_codes=plan.lot_account_codes,
                lot_asset_codes=plan.lot_asset_codes,
                lot_purchase_month=plan.lot_purchase_month,
                lot_id_codes=plan.lot_id_codes,
                agent_code=policy_agent,
                account_code=policy_account,
                asset_code=asset_code,
            )
            if ordered_lots.size == 0:
                continue

            available_value = current.lot_remaining[:, ordered_lots].sum(axis=1) * unit_price
            target_dollars = np.minimum(np.maximum(remaining_target, 0.0), available_value)
            target_dollars = np.where(valid_price & active_rollout, target_dollars, 0.0)
            if not np.any(target_dollars > 0.0):
                continue

            result = fifo_sell_dollars(
                lot_remaining=current.lot_remaining,
                ordered_lots=ordered_lots,
                target_dollars=target_dollars,
                unit_price=unit_price,
                cost_basis_per_unit=plan.lot_cost_basis_per_unit,
            )
            if result.oversell.any():
                raise ValueError(
                    "liquidity policy attempted to sell more than available lots: "
                    f"{plan.liquidity_policy_prefixes[policy]}"
                )

            current.lot_remaining -= result.sold_units
            if policy_cash_slot >= 0:
                current.cash[:, policy_cash_slot] += result.total_proceeds
            _record_capital_gains(
                plan,
                current,
                month=month,
                agent_code=policy_agent,
                sold_units=result.sold_units,
                gains=result.proceeds - result.cost_basis_consumed,
            )
            sale_active = result.sold_units > 0.0
            buffers.liq_disp_active[month, policy, asset_idx] |= sale_active.T
            buffers.liq_disp_units[month, policy, asset_idx] += result.sold_units.T
            buffers.liq_disp_basis[month, policy, asset_idx] += result.cost_basis_consumed.T
            buffers.liq_disp_proceeds[month, policy, asset_idx] += result.proceeds.T
            remaining_target = np.maximum(remaining_target - result.total_proceeds, 0.0)


def _apply_obligation_accruals(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for slot in range(plan.obligation_cause_codes.shape[1]):
        if plan.obligation_cause_codes[month, slot] < 0 or plan.obligation_source_kind[month, slot] < 0:
            continue
        source_kind = int(plan.obligation_source_kind[month, slot])
        source_index = int(plan.obligation_source_index[month, slot])
        amount = np.zeros(plan.rollout_count, dtype=np.float64)
        active = active_rollout.copy()

        if source_kind == SOURCE_CONFIGURED_OBLIGATION:
            amount = _amount_values(
                plan,
                kind=int(plan.obligation_amount_kind[month, slot]),
                fixed=float(plan.obligation_amount_fixed[month, slot]),
                base=float(plan.obligation_amount_base[month, slot]),
                series_index=int(plan.obligation_amount_series_index[month, slot]),
                base_month=int(plan.obligation_amount_base_month[month, slot]),
                adjustment_period=int(plan.obligation_amount_adjustment_period[month, slot]),
                month=month,
            )
        elif source_kind == SOURCE_MORTGAGE_PAYMENT:
            liab = source_index
            prop = int(plan.liability_property_slot[liab])
            active &= (
                current.liability_active[:, liab]
                & (plan.property_month[prop] < month)
                & (current.liability_principal[:, liab] > 0.0)
            )
            interest = current.liability_principal[:, liab] * float(plan.liability_annual_rate[liab]) / 12.0
            amount = np.minimum(
                current.liability_monthly_payment[:, liab], current.liability_principal[:, liab] + interest
            )
        elif source_kind == SOURCE_PROPERTY_TAX:
            prop = source_index
            active &= current.property_active[:, prop] & (plan.property_month[prop] < month)
            rate = float(plan.obligation_amount_fixed[month, slot])
            if np.isnan(rate):
                rate = float(plan.property_location_tax_rate[prop])
            ad_valorem_monthly = plan.property_initial_assessed_value[prop] * rate / 12.0
            non_ad_valorem_monthly = plan.property_special_assessment_annual_usd[prop] / 12.0
            amount = np.full(plan.rollout_count, ad_valorem_monthly + non_ad_valorem_monthly)
        elif source_kind == SOURCE_ESTIMATED_TAX:
            amount = np.full(plan.rollout_count, float(plan.tax_profile_prior_year_tax[source_index]) / 4.0)
        elif source_kind in (SOURCE_ESTIMATED_TAX_Q4, SOURCE_TAX_TRUE_UP):
            profile = source_index
            tax_year_end = (month // 12 - 1) * 12 + 11
            actual = _actual_tax_for_profile_year(plan, current, profile_index=profile, year_end_month=tax_year_end)
            safe_harbor = np.minimum(float(plan.tax_profile_prior_year_tax[profile]), actual)
            paid_before_q4 = float(plan.tax_profile_prior_year_tax[profile]) * 0.75
            if source_kind == SOURCE_ESTIMATED_TAX_Q4:
                amount = np.maximum(safe_harbor - paid_before_q4, 0.0)
            else:
                amount = np.maximum(actual - safe_harbor, 0.0)
        else:
            continue

        active &= amount > 0.0
        if not active.any():
            continue
        buffers.obligation_active[month, slot, active] = True
        buffers.obligation_due[month, slot, active] = amount[active]


def _apply_obligation_settlement(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active = buffers.obligation_active[month]
    if not active.any():
        return

    due = buffers.obligation_due[month]
    funded = _obligation_group_funded(plan, current, month=month, active=active, due=due)
    tax_profile_count = plan.tax_profile_agent_codes.shape[0]
    tax_payment_failed = np.zeros((tax_profile_count, plan.rollout_count), dtype=np.bool_)
    tax_settlement_candidate = np.zeros((tax_profile_count, plan.rollout_count), dtype=np.float64)
    tax_settlement_candidate_year_end = np.full((tax_profile_count, plan.rollout_count), NO_CODE, dtype=np.int64)

    for slot in range(active.shape[0]):
        active_slot = active[slot]
        if not active_slot.any():
            continue
        source_kind = int(plan.obligation_source_kind[month, slot])
        source_index = int(plan.obligation_source_index[month, slot])

        if source_kind == SOURCE_TAX_TRUE_UP:
            profile = source_index
            tax_year_end = (month // 12 - 1) * 12 + 11
            actual = _actual_tax_for_profile_year(plan, current, profile_index=profile, year_end_month=tax_year_end)
            tax_settlement_candidate[profile, active_slot] = actual[active_slot]
            tax_settlement_candidate_year_end[profile, active_slot] = tax_year_end

        amount = due[slot]
        paid = active_slot & funded[slot]
        if paid.any():
            buffers.obligation_paid[month, slot, paid] = amount[paid]
            from_slot = int(plan.obligation_from_cash_slot[month, slot])
            if from_slot >= 0:
                current.cash[paid, from_slot] -= amount[paid]
            to_slot = int(plan.obligation_to_cash_slot[month, slot])
            if to_slot >= 0:
                current.cash[paid, to_slot] += amount[paid]
            if source_kind == SOURCE_MORTGAGE_PAYMENT:
                _apply_mortgage_payment(
                    plan, buffers, current, month=month, liability_slot=source_index, paid=paid, amount=amount
                )

        failed = active_slot & ~funded[slot]
        if failed.any():
            buffers.obligation_shortfall[month, slot, failed] = amount[failed]
            buffers.obligation_failure_active[month, slot, failed] = True
            first_failure = failed & (current.failed_month < 0)
            current.failed[failed] = True
            current.failed_month[first_failure] = month
            if source_kind in (SOURCE_ESTIMATED_TAX, SOURCE_ESTIMATED_TAX_Q4, SOURCE_TAX_TRUE_UP):
                tax_payment_failed[source_index, failed] = True

    _apply_tax_settlements(
        plan,
        buffers,
        current,
        month=month,
        tax_settlement_candidate=tax_settlement_candidate,
        tax_settlement_candidate_year_end=tax_settlement_candidate_year_end,
        tax_payment_failed=tax_payment_failed,
    )


def _obligation_group_funded(
    plan: CompiledSimulation, current: CurrentStateBuffers, *, month: int, active: np.ndarray, due: np.ndarray
) -> np.ndarray:
    funded = np.zeros(active.shape, dtype=np.bool_)
    for slot in range(active.shape[0]):
        active_slot = active[slot]
        if not active_slot.any():
            continue
        agent = int(plan.obligation_agent_codes[month, slot])
        from_slot = int(plan.obligation_from_cash_slot[month, slot])
        group = (plan.obligation_agent_codes[month] == agent) & (plan.obligation_from_cash_slot[month] == from_slot)
        group_due = np.where(active[group], due[group], 0.0).sum(axis=0)
        available = current.cash[:, from_slot] if from_slot >= 0 else np.zeros(plan.rollout_count, dtype=np.float64)
        funded[slot] = active_slot & (available >= group_due - 1e-9)
    return funded


def _apply_mortgage_payment(
    plan: CompiledSimulation,
    buffers: SimulationBuffers,
    current: CurrentStateBuffers,
    *,
    month: int,
    liability_slot: int,
    paid: np.ndarray,
    amount: np.ndarray,
) -> None:
    principal_before = current.liability_principal[:, liability_slot]
    interest = np.minimum(principal_before * float(plan.liability_annual_rate[liability_slot]) / 12.0, amount)
    principal = np.minimum(np.maximum(amount - interest, 0.0), principal_before)

    buffers.mortgage_payment_active[month, liability_slot, paid] = True
    buffers.mortgage_payment_interest[month, liability_slot, paid] = interest[paid]
    buffers.mortgage_payment_principal[month, liability_slot, paid] = principal[paid]
    buffers.mortgage_payment_total[month, liability_slot, paid] = amount[paid]
    current.liability_principal[paid, liability_slot] = np.maximum(0.0, principal_before[paid] - principal[paid])
    current.liability_interest_ytd[paid, liability_slot] += interest[paid]
    current.liability_principal_ytd[paid, liability_slot] += principal[paid]


def _apply_tax_settlements(
    plan: CompiledSimulation,
    buffers: SimulationBuffers,
    current: CurrentStateBuffers,
    *,
    month: int,
    tax_settlement_candidate: np.ndarray,
    tax_settlement_candidate_year_end: np.ndarray,
    tax_payment_failed: np.ndarray,
) -> None:
    for profile in range(tax_settlement_candidate.shape[0]):
        active = (tax_settlement_candidate[profile] > 0.0) & ~tax_payment_failed[profile]
        if not active.any():
            continue
        buffers.tax_settlement_active[month, profile, active] = True
        buffers.tax_settlement_amount[month, profile, active] = tax_settlement_candidate[profile, active]
        buffers.tax_settlement_year_end_month[month, profile, active] = tax_settlement_candidate_year_end[
            profile, active
        ]
        for year_end_month in np.unique(tax_settlement_candidate_year_end[profile, active]):
            if year_end_month < 0:
                continue
            year_active = active & (tax_settlement_candidate_year_end[profile] == year_end_month)
            _settle_tax_liabilities_for_profile_year(
                plan,
                current,
                profile_index=profile,
                year_end_month=int(year_end_month),
                settlement_amount=tax_settlement_candidate[profile],
                active=year_active,
            )


def _settle_tax_liabilities_for_profile_year(
    plan: CompiledSimulation,
    current: CurrentStateBuffers,
    *,
    profile_index: int,
    year_end_month: int,
    settlement_amount: np.ndarray,
    active: np.ndarray,
) -> None:
    if not active.any():
        return
    slots = np.flatnonzero(
        (plan.tax_liability_profile_index == profile_index) & (plan.tax_liability_year_end_month == year_end_month)
    )
    if slots.size == 0:
        return
    slot_amounts = current.tax_liability_amount[:, slots]
    eligible_amounts = np.where(current.tax_liability_active[:, slots], slot_amounts, 0.0)
    outstanding = eligible_amounts.sum(axis=1)
    settlement = np.where(active, settlement_amount, 0.0)
    weights = np.divide(
        eligible_amounts, outstanding[:, None], out=np.zeros_like(eligible_amounts), where=outstanding[:, None] > 0.0
    )
    settled = np.minimum(eligible_amounts, weights * settlement[:, None])
    current.tax_liability_amount[:, slots] = np.maximum(0.0, slot_amounts - settled)


def _actual_tax_for_profile_year(
    plan: CompiledSimulation, current: CurrentStateBuffers, *, profile_index: int, year_end_month: int
) -> np.ndarray:
    slots = np.flatnonzero(
        (plan.tax_liability_profile_index == profile_index) & (plan.tax_liability_year_end_month == year_end_month)
    )
    if slots.size == 0:
        return np.zeros(plan.rollout_count, dtype=np.float64)
    return np.where(current.tax_liability_active[:, slots], current.tax_liability_amount[:, slots], 0.0).sum(axis=1)


def _sale_unit_price(plan: CompiledSimulation, *, month: int, sale: int) -> np.ndarray:
    fixed_price = float(plan.sale_price_fixed[sale])
    if not np.isnan(fixed_price):
        return np.full(plan.rollout_count, fixed_price, dtype=np.float64)
    series_index = int(plan.sale_price_series_index[sale])
    return plan.external_values[series_index, :, month]


def _record_capital_gains(
    plan: CompiledSimulation,
    current: CurrentStateBuffers,
    *,
    month: int,
    agent_code: int,
    sold_units: np.ndarray,
    gains: np.ndarray,
) -> None:
    if sold_units.size == 0:
        return
    for profile in range(plan.capital_gain_agent_codes.shape[0]):
        if int(plan.capital_gain_agent_codes[profile]) != agent_code:
            continue
        for lot in range(plan.lot_id_codes.shape[0]):
            cls = (
                LONG_TERM_CAPITAL_GAIN_CODE
                if month - int(plan.lot_purchase_month[lot]) >= 12
                else SHORT_TERM_CAPITAL_GAIN_CODE
            )
            active = sold_units[:, lot] > 0.0
            current.capital_gain_active[active, profile, cls] = True
            current.capital_gain_ytd[:, profile, cls] += gains[:, lot]


def _allocate_buffers(plan: CompiledSimulation) -> SimulationBuffers:
    p = plan.slot_plan
    h = p.event_months
    s = p.snapshot_months
    r = p.rollout_count
    lot_axis = max(1, p.lot_count)
    liability_event_axis = max(1, p.liability_count)
    buffers = SimulationBuffers(
        state=StateHistoryBuffers(
            # cash_state[S, R, C]
            cash_state=np.zeros((s, r, p.cash_count), dtype=np.float64),
            # lot_state[S, R, L]
            lot_state=np.zeros((s, r, p.lot_count), dtype=np.float64),
            # ordinary_state[S, R, tax_profile_count]
            ordinary_state=np.zeros((s, r, p.tax_profile_count), dtype=np.float64),
            # capital_gain_*_state[S, R, G, classification]
            capital_gain_active_state=np.zeros((s, r, p.capital_gain_agent_count, 2), dtype=np.bool_),
            capital_gain_state=np.zeros((s, r, p.capital_gain_agent_count, 2), dtype=np.float64),
            # tax_liability_*_state[S, R, tax_liability_count]
            tax_liability_active_state=np.zeros((s, r, p.tax_liability_count), dtype=np.bool_),
            tax_liability_state=np.zeros((s, r, p.tax_liability_count), dtype=np.float64),
            # property_*_state[S, R, property_count]
            property_active_state=np.zeros((s, r, p.property_count), dtype=np.bool_),
            property_basis_state=np.zeros((s, r, p.property_count), dtype=np.float64),
            property_ownership_state=np.zeros((s, r, p.property_count), dtype=np.float64),
            property_contribution_state=np.zeros((s, r, p.property_count), dtype=np.float64),
            property_equity_state=np.zeros((s, r, p.property_count), dtype=np.float64),
            # liability_*_state[S, R, liability_count]
            liability_active_state=np.zeros((s, r, p.liability_count), dtype=np.bool_),
            liability_principal_state=np.zeros((s, r, p.liability_count), dtype=np.float64),
            liability_monthly_payment_state=np.zeros((s, r, p.liability_count), dtype=np.float64),
            liability_interest_ytd_state=np.zeros((s, r, p.liability_count), dtype=np.float64),
            liability_principal_ytd_state=np.zeros((s, r, p.liability_count), dtype=np.float64),
            # rollout failure state[S, R]
            rollout_failed_state=np.zeros((s, r), dtype=np.bool_),
            rollout_failed_month_state=np.full((s, r), NO_CODE, dtype=np.int64),
        ),
        transfers=TransferEventBuffers(
            # transfer_*[H, T, R]
            transfer_active=np.zeros((h, p.max_transfer_slots, r), dtype=np.bool_),
            transfer_amount=np.zeros((h, p.max_transfer_slots, r), dtype=np.float64),
        ),
        properties=PropertyEventBuffers(
            # property_*_active[H, P, R]
            property_transfer_active=np.zeros((h, p.property_count, r), dtype=np.bool_),
            property_purchase_active=np.zeros((h, p.property_count, r), dtype=np.bool_),
            # mortgage_*[H, max(1, B), R]
            mortgage_origination_active=np.zeros((h, liability_event_axis, r), dtype=np.bool_),
            mortgage_payment_active=np.zeros((h, liability_event_axis, r), dtype=np.bool_),
            mortgage_payment_interest=np.zeros((h, liability_event_axis, r), dtype=np.float64),
            mortgage_payment_principal=np.zeros((h, liability_event_axis, r), dtype=np.float64),
            mortgage_payment_total=np.zeros((h, liability_event_axis, r), dtype=np.float64),
        ),
        lot_dispositions=LotDispositionEventBuffers(
            # scheduled disposition buffers[H, D, max(1, L), R]
            sched_disp_active=np.zeros((h, p.scheduled_sale_count, lot_axis, r), dtype=np.bool_),
            sched_disp_units=np.zeros((h, p.scheduled_sale_count, lot_axis, r), dtype=np.float64),
            sched_disp_basis=np.zeros((h, p.scheduled_sale_count, lot_axis, r), dtype=np.float64),
            sched_disp_proceeds=np.zeros((h, p.scheduled_sale_count, lot_axis, r), dtype=np.float64),
            # liquidity disposition buffers[H, Q, A, max(1, L), R]
            liq_disp_active=np.zeros(
                (h, p.liquidity_policy_count, p.max_liquidity_policy_assets, lot_axis, r), dtype=np.bool_
            ),
            liq_disp_units=np.zeros(
                (h, p.liquidity_policy_count, p.max_liquidity_policy_assets, lot_axis, r), dtype=np.float64
            ),
            liq_disp_basis=np.zeros(
                (h, p.liquidity_policy_count, p.max_liquidity_policy_assets, lot_axis, r), dtype=np.float64
            ),
            liq_disp_proceeds=np.zeros(
                (h, p.liquidity_policy_count, p.max_liquidity_policy_assets, lot_axis, r), dtype=np.float64
            ),
        ),
        taxes=TaxEventBuffers(
            # tax accrual/breakdown buffers[H, max(1, J), R]
            tax_accrual_active=np.zeros((h, p.tax_link_count, r), dtype=np.bool_),
            tax_accrual_amount=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_ordinary=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_ltcg=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_stcg=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_standard_deduction=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_mortgage_interest_deduction=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_itemized_deduction=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_ordinary_taxable=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_capital_taxable=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_ordinary_tax=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            tax_breakdown_capital_tax=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
            # tax settlement buffers[H, max(1, tax_profile_count), R]
            tax_settlement_active=np.zeros((h, p.max_tax_settlement_slots, r), dtype=np.bool_),
            tax_settlement_amount=np.zeros((h, p.max_tax_settlement_slots, r), dtype=np.float64),
            tax_settlement_year_end_month=np.full((h, p.max_tax_settlement_slots, r), NO_CODE, dtype=np.int64),
        ),
        obligations=ObligationEventBuffers(
            # obligation buffers[H, O, R]
            obligation_active=np.zeros((h, p.max_obligation_slots, r), dtype=np.bool_),
            obligation_due=np.zeros((h, p.max_obligation_slots, r), dtype=np.float64),
            obligation_paid=np.zeros((h, p.max_obligation_slots, r), dtype=np.float64),
            obligation_shortfall=np.zeros((h, p.max_obligation_slots, r), dtype=np.float64),
            obligation_attempt_policy=np.full((h, p.max_obligation_slots, r), NO_CODE, dtype=np.int64),
            obligation_failure_active=np.zeros((h, p.max_obligation_slots, r), dtype=np.bool_),
        ),
    )
    buffers.validate(plan)
    return buffers


def _decode_run(
    plan: CompiledSimulation, buffers: SimulationBuffers, external_series: ExternalSeriesContext
) -> SimulationRun:
    events = _decode_events(plan, buffers)
    return SimulationRun(
        cash_balances=_decode_cash(plan, buffers),
        asset_lots=_decode_asset_lots(plan, buffers),
        ordinary_income_ytd=_decode_ordinary_income(plan, buffers),
        capital_gains_ytd=_decode_capital_gains(plan, buffers),
        tax_liabilities=_decode_tax_liabilities(plan, buffers),
        property_state=_decode_property_state(plan, buffers),
        property_stakes=_decode_property_stakes(plan, buffers),
        liabilities=_decode_liabilities(plan, buffers),
        rollout_status_history=_decode_rollout_status_history(plan, buffers),
        rollout_status=_decode_final_rollout_status(plan, buffers),
        events_log=events,
        series_values=external_series.series_values,
    )


def _text(plan: CompiledSimulation, code: int) -> str | None:
    if code < 0:
        return None
    return plan.strings[code]


def _frame(rows: list[dict[str, Any]], spec: Any) -> pl.DataFrame:
    if not rows:
        return spec.empty()
    return spec.normalize(pl.DataFrame(rows))


def _state_history_frame(rows: list[dict[str, Any]], spec: Any) -> pl.DataFrame:
    columns = ["rollout_index", "month_index", *(name for name in spec.schema.names() if name != "rollout_index")]
    if rows:
        return pl.DataFrame(rows).select(columns)
    schema = pl.Schema(
        {
            "rollout_index": pl.Int64(),
            "month_index": pl.Int64(),
            **{name: dtype for name, dtype in spec.schema.items() if name != "rollout_index"},
        }
    )
    return schema.to_frame()


def _decode_cash(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows = [
        {
            "rollout_index": rollout,
            "month_index": month,
            "agent_id": _text(plan, plan.cash_agent_codes[slot]),
            "account_id": _text(plan, plan.cash_account_codes[slot]),
            "balance_usd": float(buffers.cash_state[month, rollout, slot]),
        }
        for month in range(plan.horizon_months + 1)
        for rollout in range(plan.rollout_count)
        for slot in range(plan.cash_initial_balance.shape[0])
    ]
    return _state_history_frame(rows, CASH_BALANCES_FRAME)


def _decode_asset_lots(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows = [
        {
            "rollout_index": rollout,
            "month_index": month,
            "lot_id": _text(plan, plan.lot_id_codes[slot]),
            "agent_id": _text(plan, plan.lot_agent_codes[slot]),
            "account_id": _text(plan, plan.lot_account_codes[slot]),
            "asset_id": _text(plan, plan.lot_asset_codes[slot]),
            "purchase_month_index": int(plan.lot_purchase_month[slot]),
            "cost_basis_per_unit_usd": float(plan.lot_cost_basis_per_unit[slot]),
            "remaining_quantity": float(buffers.lot_state[month, rollout, slot]),
        }
        for month in range(plan.horizon_months + 1)
        for rollout in range(plan.rollout_count)
        for slot in range(plan.lot_initial_quantity.shape[0])
    ]
    return _state_history_frame(rows, ASSET_LOT_FRAME)


def _decode_ordinary_income(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows = [
        {
            "rollout_index": rollout,
            "month_index": month,
            "agent_id": _text(plan, plan.tax_profile_agent_codes[profile]),
            "ordinary_income_usd": float(buffers.ordinary_state[month, rollout, profile]),
        }
        for month in range(plan.horizon_months + 1)
        for rollout in range(plan.rollout_count)
        for profile in range(plan.tax_profile_agent_codes.shape[0])
    ]
    return _state_history_frame(rows, ORDINARY_INCOME_YTD_FRAME)


def _decode_capital_gains(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for month in range(plan.horizon_months + 1):
        for rollout in range(plan.rollout_count):
            for profile in range(plan.capital_gain_agent_codes.shape[0]):
                for cls, classification in (
                    (LONG_TERM_CAPITAL_GAIN_CODE, "ltcg"),
                    (SHORT_TERM_CAPITAL_GAIN_CODE, "stcg"),
                ):
                    if not buffers.capital_gain_active_state[month, rollout, profile, cls]:
                        continue
                    rows.append(
                        {
                            "rollout_index": rollout,
                            "month_index": month,
                            "agent_id": _text(plan, plan.capital_gain_agent_codes[profile]),
                            "classification": classification,
                            "gain_usd": float(buffers.capital_gain_state[month, rollout, profile, cls]),
                        }
                    )
    return _state_history_frame(rows, CAPITAL_GAINS_YTD_FRAME)


def _decode_tax_liabilities(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for month in range(plan.horizon_months + 1):
        for rollout in range(plan.rollout_count):
            for slot in range(plan.tax_liability_profile_index.shape[0]):
                if not buffers.tax_liability_active_state[month, rollout, slot]:
                    continue
                link = int(plan.tax_liability_link_index[slot])
                profile = int(plan.tax_liability_profile_index[slot])
                rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "agent_id": _text(plan, plan.tax_profile_agent_codes[profile]),
                        "jurisdiction_id": _text(plan, plan.tax_link_jurisdiction_codes[link]),
                        "tax_year_end_month": int(plan.tax_liability_year_end_month[slot]),
                        "amount_owed_usd": float(buffers.tax_liability_state[month, rollout, slot]),
                    }
                )
    return _state_history_frame(rows, TAX_LIABILITIES_FRAME)


def _decode_property_state(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for month in range(plan.horizon_months + 1):
        for rollout in range(plan.rollout_count):
            for prop in range(plan.property_id_codes.shape[0]):
                if not buffers.property_active_state[month, rollout, prop]:
                    continue
                rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "property_id": _text(plan, plan.property_id_codes[prop]),
                        "location_id": _text(plan, plan.property_location_codes[prop]),
                        "purchase_month_index": int(plan.property_month[prop]),
                        "adjusted_basis_usd": float(buffers.property_basis_state[month, rollout, prop]),
                    }
                )
    return _state_history_frame(rows, PROPERTY_STATE_FRAME)


def _decode_property_stakes(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for month in range(plan.horizon_months + 1):
        for rollout in range(plan.rollout_count):
            for prop in range(plan.property_id_codes.shape[0]):
                if not buffers.property_active_state[month, rollout, prop]:
                    continue
                rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "property_id": _text(plan, plan.property_id_codes[prop]),
                        "agent_id": _text(plan, plan.property_buyer_agent_codes[prop]),
                        "ownership_pct": float(buffers.property_ownership_state[month, rollout, prop]),
                        "contribution_used_usd": float(buffers.property_contribution_state[month, rollout, prop]),
                        "equity_ledger_usd": float(buffers.property_equity_state[month, rollout, prop]),
                    }
                )
    return _state_history_frame(rows, PROPERTY_STAKE_FRAME)


def _decode_liabilities(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for month in range(plan.horizon_months + 1):
        for rollout in range(plan.rollout_count):
            for liab in range(plan.liability_codes.shape[0]):
                if not buffers.liability_active_state[month, rollout, liab]:
                    continue
                prop = int(plan.liability_property_slot[liab])
                rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "liability_id": _text(plan, plan.liability_codes[liab]),
                        "agent_id": _text(plan, plan.liability_agent_codes[liab]),
                        "payment_account_id": _text(plan, plan.liability_payment_account_codes[liab]),
                        "counterparty_agent_id": _text(plan, plan.liability_counterparty_agent_codes[liab]),
                        "counterparty_account_id": _text(plan, plan.liability_counterparty_account_codes[liab]),
                        "property_id": _text(plan, plan.property_id_codes[prop]),
                        "principal_usd": float(buffers.liability_principal_state[month, rollout, liab]),
                        "annual_interest_rate": float(plan.liability_annual_rate[liab]),
                        "term_months": int(plan.liability_term_months[liab]),
                        "origination_month_index": int(plan.property_month[prop]),
                        "monthly_payment_usd": float(buffers.liability_monthly_payment_state[month, rollout, liab]),
                        "interest_paid_ytd_usd": float(buffers.liability_interest_ytd_state[month, rollout, liab]),
                        "principal_paid_ytd_usd": float(buffers.liability_principal_ytd_state[month, rollout, liab]),
                    }
                )
    return _state_history_frame(rows, LIABILITY_FRAME)


def _decode_rollout_status_history(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    rows = [
        {
            "rollout_index": rollout,
            "month_index": month,
            "status": "failed_insufficient_cash" if buffers.rollout_failed_state[month, rollout] else "active",
            "failed_month": None
            if buffers.rollout_failed_month_state[month, rollout] < 0
            else int(buffers.rollout_failed_month_state[month, rollout]),
        }
        for month in range(plan.horizon_months + 1)
        for rollout in range(plan.rollout_count)
    ]
    return pl.DataFrame(
        rows,
        schema={
            "rollout_index": pl.Int64(),
            "month_index": pl.Int64(),
            "status": pl.Utf8(),
            "failed_month": pl.Int64(),
        },
    )


def _decode_final_rollout_status(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    month = plan.horizon_months
    rows = [
        {
            "rollout_index": rollout,
            "status": "failed_insufficient_cash" if buffers.rollout_failed_state[month, rollout] else "active",
            "failed_month": None
            if buffers.rollout_failed_month_state[month, rollout] < 0
            else int(buffers.rollout_failed_month_state[month, rollout]),
        }
        for rollout in range(plan.rollout_count)
    ]
    return _frame(rows, ROLLOUT_STATUS_FRAME)


def _decode_events(plan: CompiledSimulation, buffers: SimulationBuffers) -> EventLog:
    transfer_rows: list[dict[str, Any]] = []
    lot_rows: list[dict[str, Any]] = []
    tax_accrual_rows: list[dict[str, Any]] = []
    tax_breakdown_rows: list[dict[str, Any]] = []
    tax_settlement_rows: list[dict[str, Any]] = []
    obligation_rows: list[dict[str, Any]] = []
    obligation_settlement_rows: list[dict[str, Any]] = []
    property_purchase_rows: list[dict[str, Any]] = []
    mortgage_origination_rows: list[dict[str, Any]] = []
    mortgage_payment_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []

    for month in range(plan.horizon_months):
        for slot in range(plan.transfer_cause_codes.shape[1]):
            for rollout in range(plan.rollout_count):
                if not buffers.transfer_active[month, slot, rollout]:
                    continue
                transfer_rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "cause_id": _text(plan, plan.transfer_cause_codes[month, slot]),
                        "from_agent_id": _text(plan, plan.transfer_from_agent_codes[month, slot]),
                        "from_account_id": _text(plan, plan.transfer_from_account_codes[month, slot]),
                        "to_agent_id": _text(plan, plan.transfer_to_agent_codes[month, slot]),
                        "to_account_id": _text(plan, plan.transfer_to_account_codes[month, slot]),
                        "amount_usd": float(buffers.transfer_amount[month, slot, rollout]),
                        "income_category": "ordinary" if plan.transfer_income_profile_index[month, slot] >= 0 else None,
                    }
                )
        for prop in range(plan.property_id_codes.shape[0]):
            for rollout in range(plan.rollout_count):
                if not buffers.property_purchase_active[month, prop, rollout]:
                    continue
                property_purchase_rows.append(_property_purchase_row(plan, prop, rollout, month))
                if buffers.property_transfer_active[month, prop, rollout]:
                    transfer_rows.append(_property_transfer_row(plan, prop, rollout, month))
        for sale in range(plan.sale_month.shape[0]):
            for lot in range(plan.lot_id_codes.shape[0]):
                for rollout in range(plan.rollout_count):
                    if not buffers.sched_disp_active[month, sale, lot, rollout]:
                        continue
                    lot_rows.append(
                        _lot_row(
                            plan,
                            rollout=rollout,
                            month=month,
                            cause_id=_text(plan, plan.sale_cause_codes[month, sale]),
                            agent_code=plan.sale_agent_codes[sale],
                            source_account_code=plan.sale_source_account_codes[sale],
                            asset_code=plan.sale_asset_codes[sale],
                            lot=lot,
                            units=float(buffers.sched_disp_units[month, sale, lot, rollout]),
                            basis=float(buffers.sched_disp_basis[month, sale, lot, rollout]),
                            proceeds=float(buffers.sched_disp_proceeds[month, sale, lot, rollout]),
                            proceeds_account_code=plan.sale_proceeds_account_codes[sale],
                        )
                    )
        for policy in range(plan.liquidity_policy_agent_codes.shape[0]):
            for asset_idx in range(plan.liquidity_policy_asset_codes.shape[1]):
                asset_code = plan.liquidity_policy_asset_codes[policy, asset_idx]
                if asset_code < 0:
                    continue
                cause_id = f"{plan.liquidity_policy_prefixes[policy]}_m{month}_{_text(plan, asset_code)}"
                for lot in range(plan.lot_id_codes.shape[0]):
                    for rollout in range(plan.rollout_count):
                        if not buffers.liq_disp_active[month, policy, asset_idx, lot, rollout]:
                            continue
                        lot_rows.append(
                            _lot_row(
                                plan,
                                rollout=rollout,
                                month=month,
                                cause_id=cause_id,
                                agent_code=plan.liquidity_policy_agent_codes[policy],
                                source_account_code=plan.liquidity_policy_account_codes[policy],
                                asset_code=asset_code,
                                lot=lot,
                                units=float(buffers.liq_disp_units[month, policy, asset_idx, lot, rollout]),
                                basis=float(buffers.liq_disp_basis[month, policy, asset_idx, lot, rollout]),
                                proceeds=float(buffers.liq_disp_proceeds[month, policy, asset_idx, lot, rollout]),
                                proceeds_account_code=plan.liquidity_policy_account_codes[policy],
                            )
                        )
        for link in range(plan.tax_link_profile_index.shape[0]):
            for rollout in range(plan.rollout_count):
                if not buffers.tax_accrual_active[month, link, rollout]:
                    continue
                profile = int(plan.tax_link_profile_index[link])
                cause_id = f"{_text(plan, plan.tax_profile_agent_codes[profile])}_{_text(plan, plan.tax_link_jurisdiction_codes[link])}_year_end_accrual_m{month}"
                tax = float(buffers.tax_accrual_amount[month, link, rollout])
                tax_accrual_rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "cause_id": cause_id,
                        "agent_id": _text(plan, plan.tax_profile_agent_codes[profile]),
                        "jurisdiction_id": _text(plan, plan.tax_link_jurisdiction_codes[link]),
                        "tax_year_end_month": month,
                        "amount_usd": tax,
                    }
                )
                tax_breakdown_rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "cause_id": cause_id,
                        "agent_id": _text(plan, plan.tax_profile_agent_codes[profile]),
                        "jurisdiction_id": _text(plan, plan.tax_link_jurisdiction_codes[link]),
                        "tax_year_end_month": month,
                        "ordinary_income_usd": float(buffers.tax_breakdown_ordinary[month, link, rollout]),
                        "ltcg_usd": float(buffers.tax_breakdown_ltcg[month, link, rollout]),
                        "stcg_usd": float(buffers.tax_breakdown_stcg[month, link, rollout]),
                        "standard_deduction_usd": float(plan.tax_link_standard_deduction[link]),
                        "mortgage_interest_deduction_usd": float(
                            buffers.tax_breakdown_mortgage_interest_deduction[month, link, rollout]
                        ),
                        "itemized_deduction_usd": float(buffers.tax_breakdown_itemized_deduction[month, link, rollout]),
                        "ordinary_taxable_usd": float(buffers.tax_breakdown_ordinary_taxable[month, link, rollout]),
                        "capital_gain_taxable_usd": float(buffers.tax_breakdown_capital_taxable[month, link, rollout]),
                        "ordinary_tax_usd": float(buffers.tax_breakdown_ordinary_tax[month, link, rollout]),
                        "capital_gain_tax_usd": float(buffers.tax_breakdown_capital_tax[month, link, rollout]),
                        "total_tax_usd": tax,
                    }
                )
        for slot in range(plan.obligation_cause_codes.shape[1]):
            for rollout in range(plan.rollout_count):
                if not buffers.obligation_active[month, slot, rollout]:
                    continue
                obligation_rows.append(_obligation_row(plan, buffers, month, slot, rollout))
                obligation_settlement_rows.append(_obligation_settlement_row(plan, buffers, month, slot, rollout))
                if buffers.obligation_paid[month, slot, rollout] > 0:
                    transfer_rows.append(_obligation_transfer_row(plan, buffers, month, slot, rollout))
                if buffers.obligation_failure_active[month, slot, rollout]:
                    failure_rows.append(_failure_row(plan, buffers, month, slot, rollout))
        for liab in range(plan.liability_codes.shape[0]):
            for rollout in range(plan.rollout_count):
                if buffers.mortgage_origination_active[month, liab, rollout]:
                    mortgage_origination_rows.append(_mortgage_origination_row(plan, liab, rollout, month))
                if buffers.mortgage_payment_active[month, liab, rollout]:
                    mortgage_payment_rows.append(_mortgage_payment_row(plan, buffers, liab, rollout, month))
        for profile in range(plan.tax_profile_agent_codes.shape[0]):
            for rollout in range(plan.rollout_count):
                if not buffers.tax_settlement_active[month, profile, rollout]:
                    continue
                year_end = int(buffers.tax_settlement_year_end_month[month, profile, rollout])
                tax_year = (year_end - 11) // 12
                tax_settlement_rows.append(
                    {
                        "rollout_index": rollout,
                        "month_index": month,
                        "cause_id": f"{_text(plan, plan.tax_profile_agent_codes[profile])}_tax_settlement_y{tax_year}",
                        "agent_id": _text(plan, plan.tax_profile_agent_codes[profile]),
                        "tax_year_end_month": year_end,
                        "amount_usd": float(buffers.tax_settlement_amount[month, profile, rollout]),
                    }
                )

    return EventLog.from_frames(
        {
            "transfers": _frame(transfer_rows, EVENT_FRAMES.transfers),
            "lot_dispositions": _frame(lot_rows, EVENT_FRAMES.lot_dispositions),
            "tax_accruals": _frame(tax_accrual_rows, EVENT_FRAMES.tax_accruals),
            "tax_breakdowns": _frame(tax_breakdown_rows, EVENT_FRAMES.tax_breakdowns),
            "tax_settlements": _frame(tax_settlement_rows, EVENT_FRAMES.tax_settlements),
            "obligation_accruals": _frame(obligation_rows, EVENT_FRAMES.obligation_accruals),
            "obligation_settlements": _frame(obligation_settlement_rows, EVENT_FRAMES.obligation_settlements),
            "property_purchases": _frame(property_purchase_rows, EVENT_FRAMES.property_purchases),
            "mortgage_originations": _frame(mortgage_origination_rows, EVENT_FRAMES.mortgage_originations),
            "mortgage_payments": _frame(mortgage_payment_rows, EVENT_FRAMES.mortgage_payments),
            "rollout_failures": _frame(failure_rows, EVENT_FRAMES.rollout_failures),
        }
    )


def _property_purchase_row(plan: CompiledSimulation, prop: int, rollout: int, month: int) -> dict[str, Any]:
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": _text(plan, plan.property_cause_codes[month, prop]),
        "property_id": _text(plan, plan.property_id_codes[prop]),
        "location_id": _text(plan, plan.property_location_codes[prop]),
        "buyer_agent_id": _text(plan, plan.property_buyer_agent_codes[prop]),
        "purchase_price_usd": float(plan.property_purchase_price[prop]),
        "closing_cost_usd": float(plan.property_closing_cost[prop]),
        "adjusted_basis_usd": float(plan.property_adjusted_basis[prop]),
        "ownership_pct": float(plan.property_ownership_pct[prop]),
        "stake_contribution_usd": float(plan.property_stake_contribution[prop]),
        "equity_ledger_usd": float(plan.property_equity_ledger[prop]),
    }


def _property_transfer_row(plan: CompiledSimulation, prop: int, rollout: int, month: int) -> dict[str, Any]:
    cause = _text(plan, plan.property_cause_codes[month, prop])
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": f"{cause}_buyer_cash",
        "from_agent_id": _text(plan, plan.property_buyer_agent_codes[prop]),
        "from_account_id": _text(plan, plan.property_buyer_account_codes[prop]),
        "to_agent_id": _text(plan, plan.property_seller_agent_codes[prop]),
        "to_account_id": _text(plan, plan.property_seller_account_codes[prop]),
        "amount_usd": float(plan.property_stake_contribution[prop]),
        "income_category": None,
    }


def _lot_row(
    plan: CompiledSimulation,
    *,
    rollout: int,
    month: int,
    cause_id: str | None,
    agent_code: int,
    source_account_code: int,
    asset_code: int,
    lot: int,
    units: float,
    basis: float,
    proceeds: float,
    proceeds_account_code: int,
) -> dict[str, Any]:
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": cause_id,
        "agent_id": _text(plan, agent_code),
        "source_account_id": _text(plan, source_account_code),
        "asset_id": _text(plan, asset_code),
        "lot_id": _text(plan, plan.lot_id_codes[lot]),
        "purchase_month_index": int(plan.lot_purchase_month[lot]),
        "units_sold": units,
        "cost_basis_consumed_usd": basis,
        "proceeds_usd": proceeds,
        "proceeds_account_id": _text(plan, proceeds_account_code),
    }


def _obligation_row(
    plan: CompiledSimulation, buffers: SimulationBuffers, month: int, slot: int, rollout: int
) -> dict[str, Any]:
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": _text(plan, plan.obligation_cause_codes[month, slot]),
        "obligation_id": _text(plan, plan.obligation_id_codes[month, slot]),
        "obligation_type": _text(plan, plan.obligation_type_codes[month, slot]),
        "agent_id": _text(plan, plan.obligation_agent_codes[month, slot]),
        "from_account_id": _text(plan, plan.obligation_from_account_codes[month, slot]),
        "to_agent_id": _text(plan, plan.obligation_to_agent_codes[month, slot]),
        "to_account_id": _text(plan, plan.obligation_to_account_codes[month, slot]),
        "amount_due_usd": float(buffers.obligation_due[month, slot, rollout]),
    }


def _attempted_sources(plan: CompiledSimulation, policy: int) -> str:
    if policy < 0:
        return ""
    return ",".join(
        _text(plan, asset_code) or ""
        for asset_code in plan.liquidity_policy_asset_codes[policy].tolist()
        if asset_code >= 0
    )


def _obligation_settlement_row(
    plan: CompiledSimulation, buffers: SimulationBuffers, month: int, slot: int, rollout: int
) -> dict[str, Any]:
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": _text(plan, plan.obligation_cause_codes[month, slot]),
        "obligation_id": _text(plan, plan.obligation_id_codes[month, slot]),
        "obligation_type": _text(plan, plan.obligation_type_codes[month, slot]),
        "agent_id": _text(plan, plan.obligation_agent_codes[month, slot]),
        "from_account_id": _text(plan, plan.obligation_from_account_codes[month, slot]),
        "amount_due_usd": float(buffers.obligation_due[month, slot, rollout]),
        "amount_paid_usd": float(buffers.obligation_paid[month, slot, rollout]),
        "shortfall_usd": float(buffers.obligation_shortfall[month, slot, rollout]),
        "attempted_funding_sources": _attempted_sources(
            plan, int(buffers.obligation_attempt_policy[month, slot, rollout])
        ),
    }


def _obligation_transfer_row(
    plan: CompiledSimulation, buffers: SimulationBuffers, month: int, slot: int, rollout: int
) -> dict[str, Any]:
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": _text(plan, plan.obligation_cause_codes[month, slot]),
        "from_agent_id": _text(plan, plan.obligation_agent_codes[month, slot]),
        "from_account_id": _text(plan, plan.obligation_from_account_codes[month, slot]),
        "to_agent_id": _text(plan, plan.obligation_to_agent_codes[month, slot]),
        "to_account_id": _text(plan, plan.obligation_to_account_codes[month, slot]),
        "amount_usd": float(buffers.obligation_paid[month, slot, rollout]),
        "income_category": None,
    }


def _failure_row(
    plan: CompiledSimulation, buffers: SimulationBuffers, month: int, slot: int, rollout: int
) -> dict[str, Any]:
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": f"{_text(plan, plan.obligation_id_codes[month, slot])}_failure",
        "agent_id": _text(plan, plan.obligation_agent_codes[month, slot]),
        "deficit_usd": float(buffers.obligation_shortfall[month, slot, rollout]),
        "obligation_id": _text(plan, plan.obligation_id_codes[month, slot]),
        "obligation_type": _text(plan, plan.obligation_type_codes[month, slot]),
        "amount_due_usd": float(buffers.obligation_due[month, slot, rollout]),
        "amount_paid_usd": float(buffers.obligation_paid[month, slot, rollout]),
        "shortfall_usd": float(buffers.obligation_shortfall[month, slot, rollout]),
        "attempted_funding_sources": _attempted_sources(
            plan, int(buffers.obligation_attempt_policy[month, slot, rollout])
        ),
    }


def _mortgage_origination_row(plan: CompiledSimulation, liab: int, rollout: int, month: int) -> dict[str, Any]:
    prop = int(plan.liability_property_slot[liab])
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": f"{_text(plan, plan.property_cause_codes[month, prop])}_mortgage_origination",
        "liability_id": _text(plan, plan.liability_codes[liab]),
        "agent_id": _text(plan, plan.liability_agent_codes[liab]),
        "payment_account_id": _text(plan, plan.liability_payment_account_codes[liab]),
        "counterparty_agent_id": _text(plan, plan.liability_counterparty_agent_codes[liab]),
        "counterparty_account_id": _text(plan, plan.liability_counterparty_account_codes[liab]),
        "property_id": _text(plan, plan.property_id_codes[prop]),
        "principal_usd": float(plan.liability_principal[liab]),
        "annual_interest_rate": float(plan.liability_annual_rate[liab]),
        "term_months": int(plan.liability_term_months[liab]),
        "monthly_payment_usd": float(plan.liability_monthly_payment[liab]),
    }


def _mortgage_payment_row(
    plan: CompiledSimulation, buffers: SimulationBuffers, liab: int, rollout: int, month: int
) -> dict[str, Any]:
    prop = int(plan.liability_property_slot[liab])
    return {
        "rollout_index": rollout,
        "month_index": month,
        "cause_id": f"{_text(plan, plan.liability_codes[liab])}_payment_m{month}",
        "liability_id": _text(plan, plan.liability_codes[liab]),
        "agent_id": _text(plan, plan.liability_agent_codes[liab]),
        "counterparty_agent_id": _text(plan, plan.liability_counterparty_agent_codes[liab]),
        "property_id": _text(plan, plan.property_id_codes[prop]),
        "from_account_id": _text(plan, plan.liability_payment_account_codes[liab]),
        "to_account_id": _text(plan, plan.liability_counterparty_account_codes[liab]),
        "interest_usd": float(buffers.mortgage_payment_interest[month, liab, rollout]),
        "principal_usd": float(buffers.mortgage_payment_principal[month, liab, rollout]),
        "total_payment_usd": float(buffers.mortgage_payment_total[month, liab, rollout]),
    }
