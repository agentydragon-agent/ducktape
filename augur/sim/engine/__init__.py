"""Dense-array simulation engine."""

from __future__ import annotations

import numpy as np

from augur.sim.buffers import (
    CurrentStateBuffers,
    LifecycleEventBuffers,
    LotDispositionEventBuffers,
    ObligationEventBuffers,
    PropertyEventBuffers,
    SimulationBuffers,
    StateHistoryBuffers,
    TaxEventBuffers,
    TransferEventBuffers,
)
from augur.sim.codec.plan import DenseSimulationResult
from augur.sim.compiler import CompiledSimulation, compile_simulation
from augur.sim.engine.phases import (
    _apply_depreciation_accrual,
    _apply_lifecycle_events,
    _apply_liquidity_policy_sales,
    _apply_obligation_accruals,
    _apply_obligation_settlement,
    _apply_owner_occupied_month,
    _apply_pe_tenders,
    _apply_property_purchases,
    _apply_scheduled_asset_sales,
    _apply_scheduled_transfers,
    _apply_tax_accruals,
)
from augur.sim.external_series import ExternalSeriesContext
from augur.sim.run import SimulationRun
from augur.sim.runtime import load_jurisdictions_for, load_locations_for
from augur.sim.scenario import Scenario

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
    # Per-rollout state is R-last so per-step broadcasts (`current.foo[slot, :] += amount`)
    # are contiguous and `current.foo[..., r]` is a contiguous per-rollout view.
    current = CurrentStateBuffers(
        cash=np.broadcast_to(plan.cash_initial_balance[:, None], (p.cash_count, r)).copy(),
        lot_remaining=np.broadcast_to(plan.lot_initial_quantity[:, None], (p.lot_count, r)).copy(),
        ordinary_ytd=np.zeros((p.tax_profile_count, r), dtype=np.float64),
        capital_gain_active=np.zeros((p.capital_gain_agent_count, 2, r), dtype=np.bool_),
        capital_gain_ytd=np.zeros((p.capital_gain_agent_count, 2, r), dtype=np.float64),
        tax_liability_active=np.zeros((p.tax_liability_count, r), dtype=np.bool_),
        tax_liability_amount=np.zeros((p.tax_liability_count, r), dtype=np.float64),
        property_active=np.zeros((p.property_count, r), dtype=np.bool_),
        property_basis=np.zeros((p.property_count, r), dtype=np.float64),
        property_ownership=np.zeros((p.property_count, r), dtype=np.float64),
        property_contribution=np.zeros((p.property_count, r), dtype=np.float64),
        property_equity=np.zeros((p.property_count, r), dtype=np.float64),
        liability_active=np.zeros((p.liability_count, r), dtype=np.bool_),
        liability_principal=np.zeros((p.liability_count, r), dtype=np.float64),
        liability_monthly_payment=np.zeros((p.liability_count, r), dtype=np.float64),
        liability_interest_ytd=np.zeros((p.liability_count, r), dtype=np.float64),
        liability_principal_ytd=np.zeros((p.liability_count, r), dtype=np.float64),
        property_tax_ytd=np.zeros((p.tax_profile_count, r), dtype=np.float64),
        property_cumulative_depreciation=np.zeros((p.property_count, r), dtype=np.float64),
        property_depreciation_ytd=np.zeros((p.property_count, r), dtype=np.float64),
        # Broadcast the compile-time initial rented_fraction across rollouts. Lifecycle events
        # may then mutate per-(property, rollout) state at runtime.
        property_rented_fraction=np.broadcast_to(plan.property_rented_fraction[:, None], (p.property_count, r)).copy(),
        property_building_basis=np.broadcast_to(plan.property_building_basis[:, None], (p.property_count, r)).copy(),
        property_owner_occupied_months=np.zeros((p.property_count, r), dtype=np.int64),
        recapture_section_1250_ytd=np.zeros((p.tax_profile_count, r), dtype=np.float64),
        liability_rental_interest_ytd=np.zeros((p.liability_count, r), dtype=np.float64),
        failed=np.zeros(r, dtype=np.bool_),
        failed_month=np.full(r, NO_CODE, dtype=np.int64),
    )
    current.validate(p)
    return current


def _snapshot_initial_state(buffers: SimulationBuffers, current: CurrentStateBuffers) -> None:
    _snapshot_current_state(buffers, current, snapshot_index=0)


def _snapshot_current_state(buffers: SimulationBuffers, current: CurrentStateBuffers, *, snapshot_index: int) -> None:
    # Both `current.*` and `buffers.*_state[s]` are R-last; no transpose needed.
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
    buffers.property_cumulative_depreciation_state[snapshot_index] = current.property_cumulative_depreciation
    buffers.property_owner_occupied_months_state[snapshot_index] = current.property_owner_occupied_months
    buffers.rollout_failed_state[snapshot_index] = current.failed
    buffers.rollout_failed_month_state[snapshot_index] = current.failed_month


def _zero_failed_state(current: CurrentStateBuffers) -> None:
    failed = current.failed
    if not failed.any():
        return
    current.cash[:, failed] = 0.0
    current.lot_remaining[:, failed] = 0.0
    current.ordinary_ytd[:, failed] = 0.0
    current.capital_gain_ytd[:, :, failed] = 0.0
    current.tax_liability_amount[:, failed] = 0.0
    current.property_basis[:, failed] = 0.0
    current.property_ownership[:, failed] = 0.0
    current.property_contribution[:, failed] = 0.0
    current.property_equity[:, failed] = 0.0
    current.liability_principal[:, failed] = 0.0
    current.liability_monthly_payment[:, failed] = 0.0
    current.liability_interest_ytd[:, failed] = 0.0
    current.liability_principal_ytd[:, failed] = 0.0


def _run_month_step(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    _apply_lifecycle_events(plan, buffers, current, month)
    _apply_scheduled_transfers(plan, buffers, current, month)
    _apply_property_purchases(plan, buffers, current, month)
    _apply_scheduled_asset_sales(plan, buffers, current, month)
    _apply_obligation_accruals(plan, buffers, current, month)
    _apply_liquidity_policy_sales(plan, buffers, current, month)
    _apply_obligation_settlement(plan, buffers, current, month)
    # PE tender sales fire after obligation settlement so the policy compares against the
    # post-settlement liquid net worth (cash already moved out for this month's bills) and the
    # cap-gain accrual from any tender is captured by the year-end tax pass below.
    _apply_pe_tenders(plan, buffers, current, month)
    # Owner-occupied month counter: §121 24-of-60 window machinery. Increments before
    # depreciation accrual so a SetRentedFractionEvent firing this month is correctly
    # reflected (e.g., a conversion to 100% rental this month does NOT count toward §121).
    _apply_owner_occupied_month(current)
    # §168 monthly depreciation accrual for rented properties; must run before tax accruals so
    # the year-end pass sees this month's contribution in property_depreciation_ytd.
    _apply_depreciation_accrual(plan, current)
    # Tax accruals run last so December's mortgage payment has already landed its interest into
    # `liability_interest_ytd` before the year-end MID computation reads it.
    _apply_tax_accruals(plan, buffers, current, month)
    _zero_failed_state(current)
    _snapshot_current_state(buffers, current, snapshot_index=month + 1)


def _allocate_buffers(plan: CompiledSimulation) -> SimulationBuffers:
    p = plan.slot_plan
    h = p.event_months
    s = p.snapshot_months
    r = p.rollout_count
    lot_axis = max(1, p.lot_count)
    liability_event_axis = max(1, p.liability_count)
    buffers = SimulationBuffers(
        state=StateHistoryBuffers(
            # All state-history buffers are R-last per B0: (snapshot, count, R) for 2-axis
            # state, (snapshot, count_a, count_b, R) for the 3-axis capital-gain split.
            # cash_state[S, C, R]
            cash_state=np.zeros((s, p.cash_count, r), dtype=np.float64),
            # lot_state[S, L, R]
            lot_state=np.zeros((s, p.lot_count, r), dtype=np.float64),
            # ordinary_state[S, P, R]
            ordinary_state=np.zeros((s, p.tax_profile_count, r), dtype=np.float64),
            # capital_gain_*_state[S, G, classification, R]
            capital_gain_active_state=np.zeros((s, p.capital_gain_agent_count, 2, r), dtype=np.bool_),
            capital_gain_state=np.zeros((s, p.capital_gain_agent_count, 2, r), dtype=np.float64),
            # tax_liability_*_state[S, T, R]
            tax_liability_active_state=np.zeros((s, p.tax_liability_count, r), dtype=np.bool_),
            tax_liability_state=np.zeros((s, p.tax_liability_count, r), dtype=np.float64),
            # property_*_state[S, P, R]
            property_active_state=np.zeros((s, p.property_count, r), dtype=np.bool_),
            property_basis_state=np.zeros((s, p.property_count, r), dtype=np.float64),
            property_ownership_state=np.zeros((s, p.property_count, r), dtype=np.float64),
            property_contribution_state=np.zeros((s, p.property_count, r), dtype=np.float64),
            property_equity_state=np.zeros((s, p.property_count, r), dtype=np.float64),
            # liability_*_state[S, B, R]
            liability_active_state=np.zeros((s, p.liability_count, r), dtype=np.bool_),
            liability_principal_state=np.zeros((s, p.liability_count, r), dtype=np.float64),
            liability_monthly_payment_state=np.zeros((s, p.liability_count, r), dtype=np.float64),
            liability_interest_ytd_state=np.zeros((s, p.liability_count, r), dtype=np.float64),
            liability_principal_ytd_state=np.zeros((s, p.liability_count, r), dtype=np.float64),
            # property_cumulative_depreciation_state[S, P, R]
            property_cumulative_depreciation_state=np.zeros((s, p.property_count, r), dtype=np.float64),
            # property_owner_occupied_months_state[S, P, R]
            property_owner_occupied_months_state=np.zeros((s, p.property_count, r), dtype=np.int64),
            # rollout failure state[S, R] (1D R retained on trailing axis)
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
            # PE tender disposition buffers[H, PE_issuer, max(1, L), R]
            pe_disp_active=np.zeros((h, p.pe_issuer_count, lot_axis, r), dtype=np.bool_),
            pe_disp_units=np.zeros((h, p.pe_issuer_count, lot_axis, r), dtype=np.float64),
            pe_disp_basis=np.zeros((h, p.pe_issuer_count, lot_axis, r), dtype=np.float64),
            pe_disp_proceeds=np.zeros((h, p.pe_issuer_count, lot_axis, r), dtype=np.float64),
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
            tax_breakdown_salt_deduction=np.zeros((h, p.tax_link_count, r), dtype=np.float64),
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
        lifecycle=LifecycleEventBuffers(
            fired=np.zeros((max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.bool_),
            sale_gross_proceeds=np.zeros((max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.float64),
            sale_mortgage_payoff=np.zeros((max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.float64),
            sale_net_cash=np.zeros((max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.float64),
            sale_realized_gain=np.zeros((max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.float64),
            sale_recapture=np.zeros((max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.float64),
            sale_section_121_exclusion=np.zeros(
                (max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.float64
            ),
            sale_long_term_gain=np.zeros((max(1, int(plan.lifecycle_events.month.shape[0])), r), dtype=np.float64),
        ),
    )
    buffers.validate(plan)
    return buffers
