"""Engine state buffers + their plan-time shape validation.

This module owns every dataclass that holds simulation arrays:

- `CurrentStateBuffers`: per-step mutable state read+written by the run-loop phases.
- `StateHistoryBuffers`: snapshots of the above at month boundaries (read by the codec
  decoders to produce state-history frames).
- The per-domain `*EventBuffers` (Transfer, Property, LotDisposition, Tax, Obligation,
  Lifecycle): per-event-month sparse arrays of what actually fired.
- `SimulationBuffers`: bundles all of the above so the run-loop can carry one object
  through `_run_month_step`.

Lives at the top level of `augur.sim` (not under `engine/` or `codec/`) because both
sides of the encoder/decoder pair need to share it as a stable data interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from augur.sim.compiler import CompiledSimulation, SlotPlan


def _expect_array(name: str, array: np.ndarray, *, shape: tuple[int, ...], dtype: Any) -> None:
    if array.shape != shape:
        raise ValueError(f"{name} shape {array.shape} != expected {shape}")
    if array.dtype != np.dtype(dtype):
        raise ValueError(f"{name} dtype {array.dtype} != expected {np.dtype(dtype)}")


@dataclass
class StateHistoryBuffers:
    cash_state: NDArray[np.float64]
    lot_state: NDArray[np.float64]
    ordinary_state: NDArray[np.float64]
    capital_gain_active_state: NDArray[np.bool_]
    capital_gain_state: NDArray[np.float64]
    tax_liability_active_state: NDArray[np.bool_]
    tax_liability_state: NDArray[np.float64]
    property_active_state: NDArray[np.bool_]
    property_basis_state: NDArray[np.float64]
    property_ownership_state: NDArray[np.float64]
    property_contribution_state: NDArray[np.float64]
    property_equity_state: NDArray[np.float64]
    liability_active_state: NDArray[np.bool_]
    liability_principal_state: NDArray[np.float64]
    liability_monthly_payment_state: NDArray[np.float64]
    liability_interest_ytd_state: NDArray[np.float64]
    liability_principal_ytd_state: NDArray[np.float64]
    # Cumulative §168 depreciation USD per (snapshot_month, rollout, property). Monotone
    # non-decreasing; accrues monthly while a property has rented_fraction > 0. Used at sale
    # time for §1250 unrecaptured-depreciation recapture (phase 4) and at year-end for the
    # Schedule E depreciation deduction (the YTD slice is computed from the delta between
    # consecutive snapshots).
    property_cumulative_depreciation_state: NDArray[np.float64]
    # Cumulative count of owner-occupied months per (snapshot_month, rollout, property). Used
    # at sale time to compute the §121 24-of-last-60-months test by subtracting the 60-mo-ago
    # snapshot from the current cumulative count.
    property_owner_occupied_months_state: NDArray[np.int64]
    rollout_failed_state: NDArray[np.bool_]
    rollout_failed_month_state: NDArray[np.int64]

    def validate(self, plan: SlotPlan) -> None:
        s = plan.snapshot_months
        r = plan.rollout_count
        _expect_array("cash_state", self.cash_state, shape=(s, plan.cash_count, r), dtype=np.float64)
        _expect_array("lot_state", self.lot_state, shape=(s, plan.lot_count, r), dtype=np.float64)
        _expect_array("ordinary_state", self.ordinary_state, shape=(s, plan.tax_profile_count, r), dtype=np.float64)
        _expect_array(
            "capital_gain_active_state",
            self.capital_gain_active_state,
            shape=(s, plan.capital_gain_agent_count, 2, r),
            dtype=np.bool_,
        )
        _expect_array(
            "capital_gain_state",
            self.capital_gain_state,
            shape=(s, plan.capital_gain_agent_count, 2, r),
            dtype=np.float64,
        )
        _expect_array(
            "tax_liability_active_state",
            self.tax_liability_active_state,
            shape=(s, plan.tax_liability_count, r),
            dtype=np.bool_,
        )
        _expect_array(
            "tax_liability_state", self.tax_liability_state, shape=(s, plan.tax_liability_count, r), dtype=np.float64
        )
        _expect_array(
            "property_active_state", self.property_active_state, shape=(s, plan.property_count, r), dtype=np.bool_
        )
        _expect_array(
            "property_basis_state", self.property_basis_state, shape=(s, plan.property_count, r), dtype=np.float64
        )
        _expect_array(
            "property_ownership_state",
            self.property_ownership_state,
            shape=(s, plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "property_contribution_state",
            self.property_contribution_state,
            shape=(s, plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "property_equity_state", self.property_equity_state, shape=(s, plan.property_count, r), dtype=np.float64
        )
        _expect_array(
            "liability_active_state", self.liability_active_state, shape=(s, plan.liability_count, r), dtype=np.bool_
        )
        _expect_array(
            "liability_principal_state",
            self.liability_principal_state,
            shape=(s, plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "liability_monthly_payment_state",
            self.liability_monthly_payment_state,
            shape=(s, plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "liability_interest_ytd_state",
            self.liability_interest_ytd_state,
            shape=(s, plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "liability_principal_ytd_state",
            self.liability_principal_ytd_state,
            shape=(s, plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "property_cumulative_depreciation_state",
            self.property_cumulative_depreciation_state,
            shape=(s, plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "property_owner_occupied_months_state",
            self.property_owner_occupied_months_state,
            shape=(s, plan.property_count, r),
            dtype=np.int64,
        )
        _expect_array("rollout_failed_state", self.rollout_failed_state, shape=(s, r), dtype=np.bool_)
        _expect_array("rollout_failed_month_state", self.rollout_failed_month_state, shape=(s, r), dtype=np.int64)


@dataclass
class CurrentStateBuffers:
    cash: NDArray[np.float64]
    lot_remaining: NDArray[np.float64]
    ordinary_ytd: NDArray[np.float64]
    capital_gain_active: NDArray[np.bool_]
    capital_gain_ytd: NDArray[np.float64]
    tax_liability_active: NDArray[np.bool_]
    tax_liability_amount: NDArray[np.float64]
    property_active: NDArray[np.bool_]
    property_basis: NDArray[np.float64]
    property_ownership: NDArray[np.float64]
    property_contribution: NDArray[np.float64]
    property_equity: NDArray[np.float64]
    liability_active: NDArray[np.bool_]
    liability_principal: NDArray[np.float64]
    liability_monthly_payment: NDArray[np.float64]
    liability_interest_ytd: NDArray[np.float64]
    liability_principal_ytd: NDArray[np.float64]
    # Property-tax USD paid this calendar year, per (rollout, profile). Property-tax obligation
    # settlements add to this so the federal SALT pass at year-end can read accumulated SALT.
    # Zeroed in the year-end accrual after federal SALT has been consumed.
    property_tax_ytd: NDArray[np.float64]
    # Cumulative §168 depreciation per (rollout, property). Monotone non-decreasing; accrues
    # monthly while rented_fraction > 0. Used for Schedule E deduction (delta-vs-prior-year-end)
    # and §1250 recapture at sale (phase 4).
    property_cumulative_depreciation: NDArray[np.float64]
    # YTD depreciation accrued this calendar year per (rollout, property). Used at year-end to
    # deduct Schedule E depreciation from the owner's ordinary_ytd; zeroed after.
    property_depreciation_ytd: NDArray[np.float64]
    # Runtime rented_fraction per (rollout, property) (0..1). Initialized at scenario start from
    # `plan.property_rented_fraction[prop]` and mutated by `_apply_lifecycle_events` when
    # PropertyLifecycleEvent rows fire mid-horizon. Depreciation accrual, MID computation, and
    # Schedule E rental interest all read this each month.
    property_rented_fraction: NDArray[np.float64]
    # Runtime depreciable building basis per (rollout, property). Initialized from
    # `plan.property_building_basis[prop]` and bumped by `CapitalImprovementEvent`. Depreciation
    # accrual multiplies this by `current.property_rented_fraction[p, r] / (27.5 × 12)` monthly.
    property_building_basis: NDArray[np.float64]
    # Cumulative count of owner-occupied months per (rollout, property). Increments by 1 each
    # month while `property_active[:, p] AND property_rented_fraction[:, p] < 1.0`. At sale
    # time the engine looks back 60 months by subtracting the 60-mo-ago snapshot — qualifies
    # for §121 if the difference is ≥ 24.
    property_owner_occupied_months: NDArray[np.int64]
    # YTD §1250 unrecaptured-depreciation gain per (rollout, tax_profile). Populated by
    # PropertySaleEvent. At year-end, federal taxes this at min(25%, marginal); CA taxes as
    # ordinary (added back to bracket input). Zeroed at year-end.
    recapture_section_1250_ytd: NDArray[np.float64]
    # Rented-share of YTD mortgage interest per (rollout, liability). Each mortgage payment
    # accrues `interest × current.property_rented_fraction[prop_of_lia, r]` into this buffer.
    # At year-end:
    #   MID owner-share interest = liability_interest_ytd - liability_rental_interest_ytd
    #   Schedule E rental interest = liability_rental_interest_ytd (deducted from ordinary_ytd).
    # Reset annually.
    liability_rental_interest_ytd: NDArray[np.float64]
    failed: NDArray[np.bool_]
    failed_month: NDArray[np.int64]

    def validate(self, plan: SlotPlan) -> None:
        r = plan.rollout_count
        _expect_array("current cash", self.cash, shape=(plan.cash_count, r), dtype=np.float64)
        _expect_array("current lot_remaining", self.lot_remaining, shape=(plan.lot_count, r), dtype=np.float64)
        _expect_array("current ordinary_ytd", self.ordinary_ytd, shape=(plan.tax_profile_count, r), dtype=np.float64)
        _expect_array(
            "current capital_gain_active",
            self.capital_gain_active,
            shape=(plan.capital_gain_agent_count, 2, r),
            dtype=np.bool_,
        )
        _expect_array(
            "current capital_gain_ytd",
            self.capital_gain_ytd,
            shape=(plan.capital_gain_agent_count, 2, r),
            dtype=np.float64,
        )
        _expect_array(
            "current tax_liability_active",
            self.tax_liability_active,
            shape=(plan.tax_liability_count, r),
            dtype=np.bool_,
        )
        _expect_array(
            "current tax_liability_amount",
            self.tax_liability_amount,
            shape=(plan.tax_liability_count, r),
            dtype=np.float64,
        )
        _expect_array("current property_active", self.property_active, shape=(plan.property_count, r), dtype=np.bool_)
        _expect_array("current property_basis", self.property_basis, shape=(plan.property_count, r), dtype=np.float64)
        _expect_array(
            "current property_ownership", self.property_ownership, shape=(plan.property_count, r), dtype=np.float64
        )
        _expect_array(
            "current property_contribution",
            self.property_contribution,
            shape=(plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array("current property_equity", self.property_equity, shape=(plan.property_count, r), dtype=np.float64)
        _expect_array(
            "current liability_active", self.liability_active, shape=(plan.liability_count, r), dtype=np.bool_
        )
        _expect_array(
            "current liability_principal", self.liability_principal, shape=(plan.liability_count, r), dtype=np.float64
        )
        _expect_array(
            "current liability_monthly_payment",
            self.liability_monthly_payment,
            shape=(plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current liability_interest_ytd",
            self.liability_interest_ytd,
            shape=(plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current liability_principal_ytd",
            self.liability_principal_ytd,
            shape=(plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current property_tax_ytd", self.property_tax_ytd, shape=(plan.tax_profile_count, r), dtype=np.float64
        )
        _expect_array(
            "current property_cumulative_depreciation",
            self.property_cumulative_depreciation,
            shape=(plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current property_depreciation_ytd",
            self.property_depreciation_ytd,
            shape=(plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current property_rented_fraction",
            self.property_rented_fraction,
            shape=(plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current property_building_basis",
            self.property_building_basis,
            shape=(plan.property_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current property_owner_occupied_months",
            self.property_owner_occupied_months,
            shape=(plan.property_count, r),
            dtype=np.int64,
        )
        _expect_array(
            "current recapture_section_1250_ytd",
            self.recapture_section_1250_ytd,
            shape=(plan.tax_profile_count, r),
            dtype=np.float64,
        )
        _expect_array(
            "current liability_rental_interest_ytd",
            self.liability_rental_interest_ytd,
            shape=(plan.liability_count, r),
            dtype=np.float64,
        )
        _expect_array("current failed", self.failed, shape=(r,), dtype=np.bool_)
        _expect_array("current failed_month", self.failed_month, shape=(r,), dtype=np.int64)


@dataclass
class LifecycleEventBuffers:
    """Per-(lifecycle_event_index, rollout) tracking for deterministic lifecycle events.

    `fired[e, r]` = True iff event `e` fired on rollout `r` (i.e., the rollout was not failed
    when the event month arrived). Sale events also populate the per-amount arrays at the
    moment of the sale; for non-sale kinds those arrays stay zero.
    """

    fired: NDArray[np.bool_]
    sale_gross_proceeds: NDArray[np.float64]
    sale_mortgage_payoff: NDArray[np.float64]
    sale_net_cash: NDArray[np.float64]
    sale_realized_gain: NDArray[np.float64]
    sale_recapture: NDArray[np.float64]
    sale_section_121_exclusion: NDArray[np.float64]
    sale_long_term_gain: NDArray[np.float64]

    def validate(self, plan: SlotPlan, event_count: int) -> None:
        shape = (max(1, event_count), plan.rollout_count)
        _expect_array("lifecycle_fired", self.fired, shape=shape, dtype=np.bool_)
        for name, arr in [
            ("sale_gross_proceeds", self.sale_gross_proceeds),
            ("sale_mortgage_payoff", self.sale_mortgage_payoff),
            ("sale_net_cash", self.sale_net_cash),
            ("sale_realized_gain", self.sale_realized_gain),
            ("sale_recapture", self.sale_recapture),
            ("sale_section_121_exclusion", self.sale_section_121_exclusion),
            ("sale_long_term_gain", self.sale_long_term_gain),
        ]:
            _expect_array(name, arr, shape=shape, dtype=np.float64)


@dataclass
class TransferEventBuffers:
    transfer_active: NDArray[np.bool_]
    transfer_amount: NDArray[np.float64]

    def validate(self, plan: SlotPlan) -> None:
        shape = (plan.event_months, plan.max_transfer_slots, plan.rollout_count)
        _expect_array("transfer_active", self.transfer_active, shape=shape, dtype=np.bool_)
        _expect_array("transfer_amount", self.transfer_amount, shape=shape, dtype=np.float64)


@dataclass
class PropertyEventBuffers:
    property_transfer_active: NDArray[np.bool_]
    property_purchase_active: NDArray[np.bool_]
    mortgage_origination_active: NDArray[np.bool_]
    mortgage_payment_active: NDArray[np.bool_]
    mortgage_payment_interest: NDArray[np.float64]
    mortgage_payment_principal: NDArray[np.float64]
    mortgage_payment_total: NDArray[np.float64]

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
    sched_disp_active: NDArray[np.bool_]
    sched_disp_units: NDArray[np.float64]
    sched_disp_basis: NDArray[np.float64]
    sched_disp_proceeds: NDArray[np.float64]
    liq_disp_active: NDArray[np.bool_]
    liq_disp_units: NDArray[np.float64]
    liq_disp_basis: NDArray[np.float64]
    liq_disp_proceeds: NDArray[np.float64]
    pe_disp_active: NDArray[np.bool_]
    pe_disp_units: NDArray[np.float64]
    pe_disp_basis: NDArray[np.float64]
    pe_disp_proceeds: NDArray[np.float64]

    def validate(self, plan: SlotPlan) -> None:
        h = plan.event_months
        r = plan.rollout_count
        lot_axis = max(1, plan.lot_count)
        scheduled_shape = (h, plan.scheduled_sale_count, lot_axis, r)
        liquidity_shape = (h, plan.liquidity_policy_count, plan.max_liquidity_policy_assets, lot_axis, r)
        pe_shape = (h, plan.pe_issuer_count, lot_axis, r)
        _expect_array("sched_disp_active", self.sched_disp_active, shape=scheduled_shape, dtype=np.bool_)
        _expect_array("sched_disp_units", self.sched_disp_units, shape=scheduled_shape, dtype=np.float64)
        _expect_array("sched_disp_basis", self.sched_disp_basis, shape=scheduled_shape, dtype=np.float64)
        _expect_array("sched_disp_proceeds", self.sched_disp_proceeds, shape=scheduled_shape, dtype=np.float64)
        _expect_array("liq_disp_active", self.liq_disp_active, shape=liquidity_shape, dtype=np.bool_)
        _expect_array("liq_disp_units", self.liq_disp_units, shape=liquidity_shape, dtype=np.float64)
        _expect_array("liq_disp_basis", self.liq_disp_basis, shape=liquidity_shape, dtype=np.float64)
        _expect_array("liq_disp_proceeds", self.liq_disp_proceeds, shape=liquidity_shape, dtype=np.float64)
        _expect_array("pe_disp_active", self.pe_disp_active, shape=pe_shape, dtype=np.bool_)
        _expect_array("pe_disp_units", self.pe_disp_units, shape=pe_shape, dtype=np.float64)
        _expect_array("pe_disp_basis", self.pe_disp_basis, shape=pe_shape, dtype=np.float64)
        _expect_array("pe_disp_proceeds", self.pe_disp_proceeds, shape=pe_shape, dtype=np.float64)


@dataclass
class TaxEventBuffers:
    tax_accrual_active: NDArray[np.bool_]
    tax_accrual_amount: NDArray[np.float64]
    tax_breakdown_ordinary: NDArray[np.float64]
    tax_breakdown_ltcg: NDArray[np.float64]
    tax_breakdown_stcg: NDArray[np.float64]
    tax_breakdown_standard_deduction: NDArray[np.float64]
    tax_breakdown_mortgage_interest_deduction: NDArray[np.float64]
    tax_breakdown_salt_deduction: NDArray[np.float64]
    tax_breakdown_itemized_deduction: NDArray[np.float64]
    tax_breakdown_ordinary_taxable: NDArray[np.float64]
    tax_breakdown_capital_taxable: NDArray[np.float64]
    tax_breakdown_ordinary_tax: NDArray[np.float64]
    tax_breakdown_capital_tax: NDArray[np.float64]
    tax_settlement_active: NDArray[np.bool_]
    tax_settlement_amount: NDArray[np.float64]
    tax_settlement_year_end_month: NDArray[np.int64]

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
            "tax_breakdown_salt_deduction", self.tax_breakdown_salt_deduction, shape=tax_link_shape, dtype=np.float64
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
    obligation_active: NDArray[np.bool_]
    obligation_due: NDArray[np.float64]
    obligation_paid: NDArray[np.float64]
    obligation_shortfall: NDArray[np.float64]
    obligation_attempt_policy: NDArray[np.int64]
    obligation_failure_active: NDArray[np.bool_]

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
    lifecycle: LifecycleEventBuffers

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
        self.lifecycle.validate(slot_plan, event_count=int(plan.lifecycle_events.month.shape[0]))

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
    def property_cumulative_depreciation_state(self) -> np.ndarray:
        return self.state.property_cumulative_depreciation_state

    @property
    def property_owner_occupied_months_state(self) -> np.ndarray:
        return self.state.property_owner_occupied_months_state

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
    def pe_disp_active(self) -> np.ndarray:
        return self.lot_dispositions.pe_disp_active

    @property
    def pe_disp_units(self) -> np.ndarray:
        return self.lot_dispositions.pe_disp_units

    @property
    def pe_disp_basis(self) -> np.ndarray:
        return self.lot_dispositions.pe_disp_basis

    @property
    def pe_disp_proceeds(self) -> np.ndarray:
        return self.lot_dispositions.pe_disp_proceeds

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
    def tax_breakdown_salt_deduction(self) -> np.ndarray:
        return self.taxes.tax_breakdown_salt_deduction

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

    @property
    def lifecycle_fired(self) -> np.ndarray:
        return self.lifecycle.fired

    @property
    def lifecycle_sale_gross_proceeds(self) -> np.ndarray:
        return self.lifecycle.sale_gross_proceeds

    @property
    def lifecycle_sale_mortgage_payoff(self) -> np.ndarray:
        return self.lifecycle.sale_mortgage_payoff

    @property
    def lifecycle_sale_net_cash(self) -> np.ndarray:
        return self.lifecycle.sale_net_cash

    @property
    def lifecycle_sale_realized_gain(self) -> np.ndarray:
        return self.lifecycle.sale_realized_gain

    @property
    def lifecycle_sale_recapture(self) -> np.ndarray:
        return self.lifecycle.sale_recapture

    @property
    def lifecycle_sale_section_121_exclusion(self) -> np.ndarray:
        return self.lifecycle.sale_section_121_exclusion

    @property
    def lifecycle_sale_long_term_gain(self) -> np.ndarray:
        return self.lifecycle.sale_long_term_gain
