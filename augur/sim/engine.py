"""Dense-array simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

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
from augur.sim.compiler import (
    LIFECYCLE_KIND_CAPITAL_IMPROVEMENT,
    LIFECYCLE_KIND_FRACTION,
    LIFECYCLE_KIND_SALE,
    CompiledSimulation,
    compile_simulation,
)
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


def _apply_scheduled_transfers(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for slot in range(plan.transfers.cause.shape[1]):
        if plan.transfers.cause[month, slot] < 0:
            continue
        amount = _amount_values(
            plan,
            kind=int(plan.transfers.amount_kind[month, slot]),
            fixed=float(plan.transfers.amount_fixed[month, slot]),
            base=float(plan.transfers.amount_base[month, slot]),
            series_index=int(plan.transfers.amount_series[month, slot]),
            base_month=int(plan.transfers.amount_base_month[month, slot]),
            adjustment_period=int(plan.transfers.amount_period[month, slot]),
            month=month,
        )
        buffers.transfer_active[month, slot, active_rollout] = True
        buffers.transfer_amount[month, slot, active_rollout] = amount[active_rollout]
        from_slot = int(plan.transfers.from_slot[month, slot])
        if from_slot >= 0:
            current.cash[from_slot, active_rollout] -= amount[active_rollout]
        to_slot = int(plan.transfers.to_slot[month, slot])
        if to_slot >= 0:
            current.cash[to_slot, active_rollout] += amount[active_rollout]
        profile = int(plan.transfers.income_profile[month, slot])
        if profile >= 0:
            current.ordinary_ytd[profile, active_rollout] += amount[active_rollout]
        deduction_profile = int(plan.transfers.deduction_profile[month, slot])
        if deduction_profile >= 0:
            current.ordinary_ytd[deduction_profile, active_rollout] -= amount[active_rollout]


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


def _compute_tax_for_link(
    plan: CompiledSimulation, current: CurrentStateBuffers, *, link: int, salt_deduction: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Run the bracket math for one tax link, given a pre-computed SALT addition.

    Returns `(mortgage_interest_deduction, itemized_deduction, ordinary_taxable,
    capital_taxable, ordinary_tax, capital_tax)`. `salt_deduction` is zero for
    non-SALT links; for the federal SALT link it carries the capped SALT total
    that should stack onto MID inside itemized.

    §1250 unrecaptured-depreciation gain is routed by `tax_link_section_1250_rate`:
    - Federal-style links (rate > 0): the recapture stays out of the ordinary bracket
      walk. After `ordinary_tax` is known, the IRS Unrecaptured §1250 Worksheet rule
      taxes the recapture at the *lesser of* its implied marginal ordinary rate (what
      it would owe if stacked on top of `ordinary_taxable`) or the flat cap rate (25%
      on `federal_us`). The result is added to `capital_tax`.
    - State-style links (rate == 0): the recapture is added to ordinary income and
      flows through the standard bracket walk (CA treats it as ordinary).
    """

    profile = int(plan.tax.link_profile[link])
    gain_profile = int(plan.tax_profile_capital_gain_index[profile])
    ordinary = current.ordinary_ytd[profile, :]
    ltcg = current.capital_gain_ytd[gain_profile, LONG_TERM_CAPITAL_GAIN_CODE, :]
    stcg = current.capital_gain_ytd[gain_profile, SHORT_TERM_CAPITAL_GAIN_CODE, :]
    recapture = current.recapture_section_1250_ytd[profile, :]
    section_1250_rate = float(plan.tax.link_section_1250_rate[link])
    standard_deduction = float(plan.tax.link_standard_deduction[link])
    if bool(plan.mid.link_active[link]):
        # MID applies only to the owner-occupied share of interest. Rented-share interest
        # is deducted via the Schedule E hook at the top of `_apply_tax_accruals`.
        owner_interest_ytd = current.liability_interest_ytd - current.liability_rental_interest_ytd
        mortgage_interest_deduction = plan.mid.principal_ratio[link] @ owner_interest_ytd
    else:
        mortgage_interest_deduction = np.zeros(plan.rollout_count, dtype=np.float64)
    itemized_deduction = mortgage_interest_deduction + salt_deduction
    deduction_used = np.maximum(itemized_deduction, standard_deduction)

    # State-style §1250 lumps recapture into ordinary income; federal-style holds it out
    # so the IRS worksheet cap can apply after the bracket walk.
    federal_style_section_1250 = section_1250_rate > 0.0
    ordinary_for_brackets = ordinary if federal_style_section_1250 else ordinary + recapture

    ordinary_upper = plan.tax.link_ordinary_upper[link]
    ordinary_rate = plan.tax.link_ordinary_rate[link]
    ordinary_count = int(plan.tax.link_ordinary_count[link])
    if int(plan.tax.link_has_ltcg[link]) == 1:
        ordinary_taxable = np.maximum(ordinary_for_brackets + stcg - deduction_used, 0.0)
        capital_taxable = ltcg
        ordinary_tax = _apply_brackets(ordinary_taxable, upper=ordinary_upper, rate=ordinary_rate, count=ordinary_count)
        ltcg_tax = _apply_ltcg_brackets(
            ltcg,
            ordinary_taxable,
            upper=plan.tax.link_ltcg_upper[link],
            rate=plan.tax.link_ltcg_rate[link],
            count=int(plan.tax.link_ltcg_count[link]),
        )
    else:
        ordinary_taxable = np.maximum(ordinary_for_brackets + ltcg + stcg - deduction_used, 0.0)
        capital_taxable = np.zeros(plan.rollout_count, dtype=np.float64)
        ordinary_tax = _apply_brackets(ordinary_taxable, upper=ordinary_upper, rate=ordinary_rate, count=ordinary_count)
        ltcg_tax = np.zeros(plan.rollout_count, dtype=np.float64)

    if federal_style_section_1250:
        # IRS Unrecaptured §1250 Gain Worksheet: lesser of the implied marginal ordinary
        # tax on the recapture (what it would owe stacked on top of ordinary_taxable) or
        # the flat federal cap. Sub-25%-bracket taxpayers benefit from the marginal floor;
        # high-bracket taxpayers are unchanged because the 25% cap binds.
        ordinary_tax_with_recapture = _apply_brackets(
            ordinary_taxable + recapture, upper=ordinary_upper, rate=ordinary_rate, count=ordinary_count
        )
        implied_recapture_tax = np.maximum(ordinary_tax_with_recapture - ordinary_tax, 0.0)
        section_1250_tax = np.minimum(implied_recapture_tax, recapture * section_1250_rate)
    else:
        section_1250_tax = np.zeros(plan.rollout_count, dtype=np.float64)

    capital_tax = ltcg_tax + section_1250_tax
    return mortgage_interest_deduction, itemized_deduction, ordinary_taxable, capital_taxable, ordinary_tax, capital_tax


def _write_tax_link_buffers(
    plan: CompiledSimulation,
    buffers: SimulationBuffers,
    current: CurrentStateBuffers,
    *,
    link: int,
    month: int,
    active_rollout: np.ndarray,
    standard_deduction: float,
    mortgage_interest_deduction: np.ndarray,
    salt_deduction: np.ndarray,
    itemized_deduction: np.ndarray,
    ordinary_taxable: np.ndarray,
    capital_taxable: np.ndarray,
    ordinary_tax: np.ndarray,
    capital_tax: np.ndarray,
) -> np.ndarray:
    profile = int(plan.tax.link_profile[link])
    gain_profile = int(plan.tax_profile_capital_gain_index[profile])
    ordinary = current.ordinary_ytd[profile, :]
    ltcg = current.capital_gain_ytd[gain_profile, LONG_TERM_CAPITAL_GAIN_CODE, :]
    stcg = current.capital_gain_ytd[gain_profile, SHORT_TERM_CAPITAL_GAIN_CODE, :]
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
    buffers.tax_breakdown_salt_deduction[month, link, active_rollout] = salt_deduction[active_rollout]
    buffers.tax_breakdown_itemized_deduction[month, link, active_rollout] = itemized_deduction[active_rollout]
    buffers.tax_breakdown_ordinary_taxable[month, link, active_rollout] = ordinary_taxable[active_rollout]
    buffers.tax_breakdown_capital_taxable[month, link, active_rollout] = capital_taxable[active_rollout]
    buffers.tax_breakdown_ordinary_tax[month, link, active_rollout] = ordinary_tax[active_rollout]
    buffers.tax_breakdown_capital_tax[month, link, active_rollout] = capital_tax[active_rollout]

    tax_slot = _tax_liability_slot_for(plan, profile_index=profile, link_index=link, year_end_month=month)
    if tax_slot >= 0:
        current.tax_liability_active[tax_slot, active_rollout] = True
        current.tax_liability_amount[tax_slot, active_rollout] = tax[active_rollout]
    return tax


def _apply_pe_tenders(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    """Fire LNW-floor-driven private-equity tender sales for any issuer whose sampled tender
    event activates this month.

    Per issuer with a policy assignment:
      1. Look up the per-rollout boolean of "tender fires this month".
      2. If any rollout fires: read the issuer's per-rollout mark (level series).
      3. Compute the owner's liquid net worth = cash + non-PE lot value.
      4. shortfall = max(0, floor - LNW), capped by available PE value.
      5. Drain FIFO from the issuer's lots at the mark, credit proceeds to the policy's
         designated cash slot, accrue the cap gain to the owner's capital_gain_ytd.

    Multiple issuers tendering the same month are processed in array order; each updates
    cash and lot_remaining before the next issuer's LNW computation runs, so the floor
    genuinely caps aggregate sale across same-month tenders.
    """

    issuer_count = plan.pe_issuers.codes.shape[0]
    if issuer_count == 0:
        return
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for issuer_idx in range(issuer_count):
        if int(plan.pe_issuers.codes[issuer_idx]) < 0:
            continue
        policy_idx = int(plan.pe_issuers.policy_index[issuer_idx])
        event_series_idx = int(plan.pe_issuers.event_series[issuer_idx])
        level_series_idx = int(plan.pe_issuers.level_series[issuer_idx])
        if policy_idx < 0 or event_series_idx < 0 or level_series_idx < 0:
            continue
        tender_active = plan.external_event_values[event_series_idx, :, month]  # (rollout,)
        tender_active = tender_active & active_rollout
        if not tender_active.any():
            continue
        mark = plan.external_values[level_series_idx, :, month]
        mark = np.nan_to_num(mark, nan=0.0)
        valid_mark = mark > 0.0
        if not valid_mark.any():
            continue

        floor = _amount_values(
            plan,
            kind=int(plan.pe_policies.floor_kind[policy_idx]),
            fixed=float(plan.pe_policies.floor_fixed[policy_idx]),
            base=float(plan.pe_policies.floor_base[policy_idx]),
            series_index=int(plan.pe_policies.floor_series[policy_idx]),
            base_month=int(plan.pe_policies.floor_base_month[policy_idx]),
            adjustment_period=int(plan.pe_policies.floor_period[policy_idx]),
            month=month,
        )
        lnw = _compute_liquid_net_worth(plan, current, policy_idx=policy_idx, month=month)
        shortfall = np.maximum(0.0, floor - lnw)

        lot_indices = np.flatnonzero(plan.pe_issuers.lot_mask[issuer_idx])
        if lot_indices.size == 0:
            continue
        ordered_lots = lot_indices[np.argsort(plan.lot_purchase_month[lot_indices], kind="stable")]
        units_held = current.lot_remaining[ordered_lots, :].sum(axis=0)
        available_value = units_held * mark
        target_dollars = np.minimum(shortfall, available_value)
        target_dollars = np.where(tender_active & valid_mark, target_dollars, 0.0)
        if not (target_dollars > 0.0).any():
            continue

        # `fifo_sell_dollars` works in (R, L); current.lot_remaining is (L, R) per B0,
        # so transpose at the call seam.
        result = fifo_sell_dollars(
            lot_remaining=current.lot_remaining.T,
            ordered_lots=ordered_lots,
            target_dollars=target_dollars,
            unit_price=mark,
            cost_basis_per_unit=plan.lot_cost_basis_per_unit,
        )
        if result.oversell.any():
            raise ValueError(
                f"PE tender attempted to sell more than available lots for issuer "
                f"{_text(plan, plan.pe_issuers.codes[issuer_idx])}"
            )
        current.lot_remaining -= result.sold_units.T
        proceeds_slot = int(plan.pe_policies.proceeds_cash_slot[policy_idx])
        if proceeds_slot >= 0:
            current.cash[proceeds_slot, :] += result.total_proceeds
        owner_code = int(plan.pe_policies.owner_agent[policy_idx])
        _record_capital_gains(
            plan,
            current,
            month=month,
            agent_code=owner_code,
            sold_units=result.sold_units,
            gains=result.proceeds - result.cost_basis_consumed,
        )


def _compute_liquid_net_worth(
    plan: CompiledSimulation, current: CurrentStateBuffers, *, policy_idx: int, month: int
) -> np.ndarray:
    """Per-rollout LNW = cash in policy-owner accounts + non-PE-lot value at current prices."""

    owner_cash_mask = plan.pe_policies.owner_cash_mask[policy_idx]
    cash_total = (current.cash * owner_cash_mask[:, None]).sum(axis=0)
    lot_mask = plan.pe_policies.owner_non_pe_lot_mask[policy_idx]
    if not lot_mask.any():
        return cash_total
    lot_indices = np.flatnonzero(lot_mask)
    series_indices = plan.lot_asset_series_index[lot_indices]
    valid = series_indices >= 0
    safe_series_indices = np.where(valid, series_indices, 0)
    prices = plan.external_values[safe_series_indices, :, month]  # (lot, rollout)
    prices = np.where(valid[:, None], prices, 0.0)
    prices = np.nan_to_num(prices, nan=0.0)
    quantities = current.lot_remaining[lot_indices, :]  # (lot, rollout)
    lot_value = (quantities * prices).sum(axis=0)
    return cash_total + lot_value


def _apply_lifecycle_events(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    """Apply this month's PropertyLifecycleEvent rows to per-rollout runtime state.

    Three kinds share the same machinery:
    - `LIFECYCLE_KIND_FRACTION`: mutate `current.property_rented_fraction[prop, :]` to the
      event's new value.
    - `LIFECYCLE_KIND_CAPITAL_IMPROVEMENT`: debit owner's cash by `amount_usd` and increase
      `current.property_building_basis[prop, :]` by the same amount.
    - `LIFECYCLE_KIND_SALE`: dispatch to `_apply_property_sale` which also fills the per-event
      `sale_*` arrays on `buffers.lifecycle`.

    For each event that fires for an active rollout, `buffers.lifecycle.fired[event_index, r]`
    is set. The decoder turns this into a polars frame so the frontend can render markers.

    Phase 3 lifecycle events are deterministic per rollout. Future policy-driven decisions
    would emit per-rollout records; this apply machinery handles them by indexing the rollout
    subset.
    """

    starts = plan.lifecycle_events.month_starts
    if month + 1 >= starts.shape[0]:
        return
    begin = int(starts[month])
    end = int(starts[month + 1])
    if begin == end:
        return
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for i in range(begin, end):
        prop = int(plan.lifecycle_events.property_slot[i])
        kind = int(plan.lifecycle_events.kind[i])
        buffers.lifecycle_fired[i, active_rollout] = True
        if kind == LIFECYCLE_KIND_FRACTION:
            new_fraction = float(plan.lifecycle_events.rented_fraction[i])
            current.property_rented_fraction[prop, active_rollout] = new_fraction
        elif kind == LIFECYCLE_KIND_CAPITAL_IMPROVEMENT:
            amount = float(plan.lifecycle_events.amount[i])
            owner_cash_slot = int(plan.properties.buyer_slot[prop])
            if owner_cash_slot >= 0:
                current.cash[owner_cash_slot, active_rollout] -= amount
            current.property_building_basis[prop, active_rollout] += amount
        elif kind == LIFECYCLE_KIND_SALE:
            _apply_property_sale(
                plan,
                buffers,
                current,
                month=month,
                event_index=i,
                prop=prop,
                closing_cost_pct=float(plan.lifecycle_events.amount[i]),
                active_rollout=active_rollout,
            )


SECTION_121_LOOKBACK_MONTHS = 60
SECTION_121_MIN_QUALIFYING_MONTHS = 24
# Per-profile cap lives on the plan: `plan.tax.profile_section_121_exclusion[owner_profile]`.
# Compiler populates it from `_SECTION_121_EXCLUSION_USD_BY_FILING_STATUS`, which only knows the
# single-filer variant today — any other filing status raises NotImplementedError at compile
# time so no rollout silently runs with the wrong cap.


def _apply_property_sale(
    plan: CompiledSimulation,
    buffers: SimulationBuffers,
    current: CurrentStateBuffers,
    *,
    month: int,
    event_index: int,
    prop: int,
    closing_cost_pct: float,
    active_rollout: np.ndarray,
) -> None:
    """Execute a PropertySaleEvent for one property and log the per-rollout amounts.

    - Market value = purchase_price × home_value_series[t] / home_value_series[base_month].
    - Gross proceeds = market value × (1 - closing_cost_pct / 100).
    - Net proceeds to owner cash = gross - outstanding mortgage balance.
    - Realized gain = gross_proceeds - (purchase_price + capex - cumulative_depreciation).
    - §1250 recapture = min(realized_gain, cumulative_dep) → routed to a dedicated YTD bucket
      so the federal link can tax it at 25% (its dedicated rate), while CA-style links treat
      it as ordinary income inside their standard bracket walk.
    - §121: if the property was owner-occupied at least
      `SECTION_121_MIN_QUALIFYING_MONTHS` of the last `SECTION_121_LOOKBACK_MONTHS`,
      exclude up to `plan.tax.profile_section_121_exclusion[owner_profile]` of the
      post-recapture gain from LTCG. The cap is keyed on filing status at compile time.
    - Remainder = post-exclusion LTCG → added to owner's long_term_capital_gain_ytd.
    - Mortgage paid off; property frozen (property_active → False, rented_fraction → 0,
      building_basis → 0, cumulative_depreciation preserved for record).
    - Per-rollout proceeds/payoff/gain/recapture/121-exclusion/ltcg are written to
      `buffers.lifecycle.sale_*[event_index, r]`.
    """

    rollout_count = plan.rollout_count
    sale_gross_proceeds = np.zeros(rollout_count, dtype=np.float64)
    sale_mortgage_payoff = np.zeros(rollout_count, dtype=np.float64)
    sale_net_cash = np.zeros(rollout_count, dtype=np.float64)
    sale_realized_gain = np.zeros(rollout_count, dtype=np.float64)
    sale_recapture = np.zeros(rollout_count, dtype=np.float64)
    sale_section_121 = np.zeros(rollout_count, dtype=np.float64)
    sale_long_term_gain = np.zeros(rollout_count, dtype=np.float64)

    series_idx = int(plan.property_home_value_series_index[prop])
    if series_idx < 0:
        # No home_value series available — skip sale (engineer error in scenario; should be
        # surfaced at compile time but we tolerate gracefully here).
        return
    base_value = plan.external_values[series_idx, :, 0]  # per-rollout, base month
    sale_value_series = plan.external_values[series_idx, :, month]  # per-rollout, sale month
    purchase_price = float(plan.properties.purchase_price[prop])
    market_value = purchase_price * sale_value_series / base_value  # (R,)
    gross_proceeds = market_value * (1.0 - closing_cost_pct / 100.0)

    # Adjusted basis = (purchase_price + capex done) - cumulative depreciation. The runtime
    # building_basis includes capex bumps but excludes land; reconstitute full basis below.
    initial_building_basis = float(plan.property_building_basis[prop])
    capex = current.property_building_basis[prop, :] - initial_building_basis
    cum_dep = current.property_cumulative_depreciation[prop, :]
    adjusted_basis = purchase_price + capex - cum_dep
    realized_gain = gross_proceeds - adjusted_basis
    recapture = np.minimum(np.maximum(realized_gain, 0.0), cum_dep)
    post_recapture_gain = np.maximum(realized_gain - recapture, 0.0)

    # §121 ownership/use test: count owner-occupied months in the last
    # SECTION_121_LOOKBACK_MONTHS. `property_owner_occupied_months` is cumulative-since-purchase
    # and is only incremented this month after `_apply_lifecycle_events` returns; subtracting
    # the lookback snapshot gives the count of qualifying months strictly inside the window.
    current_cum = current.property_owner_occupied_months[prop, :].astype(np.int64)
    lookback_snapshot_index = max(0, month - SECTION_121_LOOKBACK_MONTHS)
    snapshot_cum = buffers.property_owner_occupied_months_state[lookback_snapshot_index, prop, :].astype(np.int64)
    months_in_window = current_cum - snapshot_cum
    qualifies = months_in_window >= SECTION_121_MIN_QUALIFYING_MONTHS
    owner_profile = int(plan.property_owner_profile_index[prop])
    # `property_owner_profile_index` is filled at compile time; a property with no tax owner
    # (sentinel -1) means there's nobody to exclude for, so §121 collapses to 0.
    exclusion_cap = float(plan.tax.profile_section_121_exclusion[owner_profile]) if owner_profile >= 0 else 0.0
    section_121_exclusion = np.where(qualifies, np.minimum(post_recapture_gain, exclusion_cap), 0.0)
    ltcg = post_recapture_gain - section_121_exclusion

    owner_cash_slot = int(plan.properties.buyer_slot[prop])
    # Pay off any outstanding mortgage on this property; net cash to owner = gross - payoff.
    mortgage_payoff = np.zeros(rollout_count, dtype=np.float64)
    for lia in range(int(plan.liabilities.property_slot.shape[0])):
        if int(plan.liabilities.property_slot[lia]) == prop:
            mortgage_payoff += current.liability_principal[lia, :]
            current.liability_principal[lia, :] = 0.0
            current.liability_active[lia, :] = False

    net_cash = gross_proceeds - mortgage_payoff
    if owner_cash_slot >= 0:
        current.cash[owner_cash_slot, active_rollout] += net_cash[active_rollout]

    # Tax routing: recapture goes to its own YTD bucket (federal cap dispatch happens in
    # `_compute_tax_for_link`); the post-recapture, post-§121 remainder is LTCG.
    # `owner_profile` was already resolved above for the §121 cap lookup.
    if owner_profile >= 0:
        current.recapture_section_1250_ytd[owner_profile, active_rollout] += recapture[active_rollout]
        gain_profile = int(plan.tax_profile_capital_gain_index[owner_profile])
        if gain_profile >= 0:
            current.capital_gain_ytd[gain_profile, LONG_TERM_CAPITAL_GAIN_CODE, active_rollout] += ltcg[active_rollout]
            current.capital_gain_active[gain_profile, LONG_TERM_CAPITAL_GAIN_CODE, active_rollout] = True

    # Freeze property state. cumulative_depreciation preserved as a historical record.
    current.property_active[prop, active_rollout] = False
    current.property_rented_fraction[prop, active_rollout] = 0.0
    current.property_building_basis[prop, active_rollout] = 0.0

    # Log per-rollout amounts (zero on failed rollouts).
    sale_gross_proceeds[active_rollout] = gross_proceeds[active_rollout]
    sale_mortgage_payoff[active_rollout] = mortgage_payoff[active_rollout]
    sale_net_cash[active_rollout] = net_cash[active_rollout]
    sale_realized_gain[active_rollout] = realized_gain[active_rollout]
    sale_recapture[active_rollout] = recapture[active_rollout]
    sale_section_121[active_rollout] = section_121_exclusion[active_rollout]
    sale_long_term_gain[active_rollout] = ltcg[active_rollout]
    buffers.lifecycle_sale_gross_proceeds[event_index] = sale_gross_proceeds
    buffers.lifecycle_sale_mortgage_payoff[event_index] = sale_mortgage_payoff
    buffers.lifecycle_sale_net_cash[event_index] = sale_net_cash
    buffers.lifecycle_sale_realized_gain[event_index] = sale_realized_gain
    buffers.lifecycle_sale_recapture[event_index] = sale_recapture
    buffers.lifecycle_sale_section_121_exclusion[event_index] = sale_section_121
    buffers.lifecycle_sale_long_term_gain[event_index] = sale_long_term_gain


def _apply_owner_occupied_month(current: CurrentStateBuffers) -> None:
    """Increment per-property owner-occupied-month counters for §121 tracking.

    A property is "owner-occupied this month" if it's active and rented_fraction < 1.0 (at
    least partial owner residence). The cumulative count is the §121 base; the
    snapshot history lets the sale handler compute the 24-of-last-60-months window.
    """

    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    property_count = current.property_rented_fraction.shape[0]
    for prop in range(property_count):
        owner_occupied = (
            active_rollout & current.property_active[prop, :] & (current.property_rented_fraction[prop, :] < 1.0)
        )
        current.property_owner_occupied_months[prop, owner_occupied] += 1


def _apply_depreciation_accrual(plan: CompiledSimulation, current: CurrentStateBuffers) -> None:
    """Accrue §168 straight-line depreciation for each rented property.

    Monthly depreciation = `building_basis × current.property_rented_fraction / (27.5 × 12)`.
    Reads the runtime `current.property_rented_fraction[p, r]` so mid-horizon lifecycle
    events (StartRenting/StopRenting/ChangeRentalPlan) take effect immediately. Updates both
    the cumulative buffer (used for §1250 recapture at sale) and the YTD buffer (read at
    year-end by `_apply_tax_accruals` to net Schedule E depreciation against ordinary income).
    """

    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    property_count = current.property_rented_fraction.shape[0]
    for prop in range(property_count):
        active_for_property = active_rollout & current.property_active[prop, :]
        if not active_for_property.any():
            continue
        # Both rented_fraction and building_basis are runtime per-rollout state — they may
        # have been mutated by PropertyLifecycleEvent rows this month.
        rented = current.property_rented_fraction[prop, :]
        basis = current.property_building_basis[prop, :]
        monthly_dep = basis * rented / (27.5 * 12.0)
        current.property_cumulative_depreciation[prop, active_for_property] += monthly_dep[active_for_property]
        current.property_depreciation_ytd[prop, active_for_property] += monthly_dep[active_for_property]


def _apply_tax_accruals(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if month % 12 != 11 or not active_rollout.any():
        return

    # Schedule E rental interest deduction: for each liability, the YTD rented-share interest
    # (accumulated per-month against the runtime `current.property_rented_fraction`) deducts
    # from the owner's ordinary_ytd. The owner share is fed into MID below. This must run
    # before the bracket walk reads ordinary_ytd.
    liability_count = current.liability_rental_interest_ytd.shape[0]
    for lia in range(liability_count):
        profile = int(plan.liability_owner_profile_index[lia])
        if profile < 0:
            continue
        schedule_e_interest = current.liability_rental_interest_ytd[lia, :]
        if not bool((schedule_e_interest != 0.0).any()):
            continue
        current.ordinary_ytd[profile, active_rollout] -= schedule_e_interest[active_rollout]

    # Schedule E §168 depreciation deduction: the YTD depreciation accrued this calendar year
    # for each rented property deducts from the owner's ordinary_ytd. Then reset YTD.
    property_count = plan.property_owner_profile_index.shape[0]
    for prop in range(property_count):
        profile = int(plan.property_owner_profile_index[prop])
        if profile < 0:
            continue
        ytd = current.property_depreciation_ytd[prop, :]
        if not bool((ytd != 0.0).any()):
            continue
        current.ordinary_ytd[profile, active_rollout] -= ytd[active_rollout]
    current.property_depreciation_ytd[:, active_rollout] = 0.0

    link_count = plan.tax.link_profile.shape[0]
    # First pass: every link that isn't a SALT-active federal link. Stash its annual tax so
    # the SALT pass can sum state-link contributions per federal link.
    annual_tax_by_link = np.zeros((plan.rollout_count, max(1, link_count)), dtype=np.float64)
    zero_salt = np.zeros(plan.rollout_count, dtype=np.float64)
    for link in range(link_count):
        if bool(plan.salt.link_active[link]):
            continue
        standard_deduction = float(plan.tax.link_standard_deduction[link])
        (
            mortgage_interest_deduction,
            itemized_deduction,
            ordinary_taxable,
            capital_taxable,
            ordinary_tax,
            capital_tax,
        ) = _compute_tax_for_link(plan, current, link=link, salt_deduction=zero_salt)
        tax = _write_tax_link_buffers(
            plan,
            buffers,
            current,
            link=link,
            month=month,
            active_rollout=active_rollout,
            standard_deduction=standard_deduction,
            mortgage_interest_deduction=mortgage_interest_deduction,
            salt_deduction=zero_salt,
            itemized_deduction=itemized_deduction,
            ordinary_taxable=ordinary_taxable,
            capital_taxable=capital_taxable,
            ordinary_tax=ordinary_tax,
            capital_tax=capital_tax,
        )
        annual_tax_by_link[:, link] = tax

    # Second pass: SALT-active federal links. SALT = property tax YTD for this profile + sum of
    # contributing-state-link annual tax, all capped per the year's schedule entry.
    year_index = month // 12
    cap_year_index = min(year_index, plan.salt.cap_by_year.shape[1] - 1)
    for link in range(link_count):
        if not bool(plan.salt.link_active[link]):
            continue
        profile = int(plan.tax.link_profile[link])
        state_tax_total = annual_tax_by_link @ plan.salt.contributing_mask[link].astype(np.float64)
        salt_total = current.property_tax_ytd[profile, :] + state_tax_total
        cap = float(plan.salt.cap_by_year[link, cap_year_index])
        salt_deduction = np.minimum(salt_total, cap)
        standard_deduction = float(plan.tax.link_standard_deduction[link])
        (
            mortgage_interest_deduction,
            itemized_deduction,
            ordinary_taxable,
            capital_taxable,
            ordinary_tax,
            capital_tax,
        ) = _compute_tax_for_link(plan, current, link=link, salt_deduction=salt_deduction)
        tax = _write_tax_link_buffers(
            plan,
            buffers,
            current,
            link=link,
            month=month,
            active_rollout=active_rollout,
            standard_deduction=standard_deduction,
            mortgage_interest_deduction=mortgage_interest_deduction,
            salt_deduction=salt_deduction,
            itemized_deduction=itemized_deduction,
            ordinary_taxable=ordinary_taxable,
            capital_taxable=capital_taxable,
            ordinary_tax=ordinary_tax,
            capital_tax=capital_tax,
        )
        annual_tax_by_link[:, link] = tax

    for profile in range(current.ordinary_ytd.shape[0]):
        current.ordinary_ytd[profile, active_rollout] = 0.0
        gain_profile = int(plan.tax_profile_capital_gain_index[profile])
        ltcg_active = active_rollout & current.capital_gain_active[gain_profile, LONG_TERM_CAPITAL_GAIN_CODE, :]
        stcg_active = active_rollout & current.capital_gain_active[gain_profile, SHORT_TERM_CAPITAL_GAIN_CODE, :]
        current.capital_gain_ytd[gain_profile, LONG_TERM_CAPITAL_GAIN_CODE, ltcg_active] = 0.0
        current.capital_gain_ytd[gain_profile, SHORT_TERM_CAPITAL_GAIN_CODE, stcg_active] = 0.0
    # Zero YTD interest at year-end so next year's MID accumulation starts fresh. Mirrors the
    # ordinary/capital-gain YTD resets above.
    current.liability_interest_ytd[:, active_rollout] = 0.0
    current.liability_rental_interest_ytd[:, active_rollout] = 0.0
    # Same treatment for property-tax YTD; the federal SALT pass above has consumed it.
    current.property_tax_ytd[:, active_rollout] = 0.0
    # §1250 recapture YTD: consumed by both federal (flat 25%) and state (ordinary brackets)
    # links above. Reset so next year's recapture from a separate sale starts fresh.
    current.recapture_section_1250_ytd[:, active_rollout] = 0.0


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
        (plan.tax_liabilities.profile_index == profile_index)
        & (plan.tax_liabilities.link_index == link_index)
        & (plan.tax_liabilities.year_end_month == year_end_month)
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
    for prop in range(plan.properties.month.shape[0]):
        if plan.properties.month[prop] != month:
            continue
        buffers.property_purchase_active[month, prop, active_rollout] = True
        current.property_active[prop, active_rollout] = True
        current.property_basis[prop, active_rollout] = plan.properties.adjusted_basis[prop]
        current.property_ownership[prop, active_rollout] = plan.properties.ownership[prop]
        current.property_contribution[prop, active_rollout] = plan.properties.stake_contribution[prop]
        current.property_equity[prop, active_rollout] = plan.properties.equity_ledger[prop]

        buyer_cash = float(plan.properties.stake_contribution[prop])
        if buyer_cash > 0.0:
            buffers.property_transfer_active[month, prop, active_rollout] = True
            buyer_slot = int(plan.properties.buyer_slot[prop])
            if buyer_slot >= 0:
                current.cash[buyer_slot, active_rollout] -= buyer_cash
            seller_slot = int(plan.properties.seller_slot[prop])
            if seller_slot >= 0:
                current.cash[seller_slot, active_rollout] += buyer_cash

        liability_slot = int(plan.properties.mortgage_slot[prop])
        if liability_slot >= 0:
            buffers.mortgage_origination_active[month, liability_slot, active_rollout] = True
            current.liability_active[liability_slot, active_rollout] = True
            current.liability_principal[liability_slot, active_rollout] = plan.liabilities.principal[liability_slot]
            current.liability_monthly_payment[liability_slot, active_rollout] = plan.liabilities.monthly_payment[
                liability_slot
            ]
            current.liability_interest_ytd[liability_slot, active_rollout] = 0.0
            current.liability_principal_ytd[liability_slot, active_rollout] = 0.0


def _apply_scheduled_asset_sales(
    plan: CompiledSimulation, buffers: SimulationBuffers, current: CurrentStateBuffers, month: int
) -> None:
    active_rollout = ~current.failed
    if not active_rollout.any():
        return
    for sale in range(plan.sales.month.shape[0]):
        if plan.sales.month[sale] != month:
            continue
        ordered_lots = lot_order_for_pool(
            lot_agent_codes=plan.lot_agent_codes,
            lot_account_codes=plan.lot_account_codes,
            lot_asset_codes=plan.lot_asset_codes,
            lot_purchase_month=plan.lot_purchase_month,
            lot_id_codes=plan.lot_id_codes,
            agent_code=int(plan.sales.agent[sale]),
            account_code=int(plan.sales.source_account[sale]),
            asset_code=int(plan.sales.asset[sale]),
        )
        target_units = np.where(active_rollout, float(plan.sales.quantity[sale]), 0.0)
        price = _sale_unit_price(plan, month=month, sale=sale)
        result = fifo_sell_units(
            lot_remaining=current.lot_remaining.T,
            ordered_lots=ordered_lots,
            target_units=target_units,
            unit_price=price,
            cost_basis_per_unit=plan.lot_cost_basis_per_unit,
        )
        if result.oversell.any():
            raise ValueError(
                f"scheduled asset sale exceeds available lots: {_text(plan, plan.sales.cause[month, sale])}"
            )

        current.lot_remaining -= result.sold_units.T
        proceeds_slot = int(plan.sales.proceeds_slot[sale])
        if proceeds_slot >= 0:
            current.cash[proceeds_slot, :] += result.total_proceeds
        _record_capital_gains(
            plan,
            current,
            month=month,
            agent_code=int(plan.sales.agent[sale]),
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
    for policy in range(plan.liquidity_policies.agent.shape[0]):
        policy_agent = int(plan.liquidity_policies.agent[policy])
        policy_account = int(plan.liquidity_policies.account[policy])
        policy_cash_slot = int(plan.liquidity_policies.cash_slot[policy])

        matching_obligations = np.flatnonzero(
            (plan.obligations.agent[month] == policy_agent) & (plan.obligations.from_slot[month] == policy_cash_slot)
        )
        if matching_obligations.size:
            matching_active = obligation_active[matching_obligations]
            hard_demand = np.where(matching_active, obligation_due[matching_obligations], 0.0).sum(axis=0)
            for row, slot in enumerate(matching_obligations):
                buffers.obligation_attempt_policy[month, slot, matching_active[row]] = policy
        else:
            hard_demand = np.zeros(plan.rollout_count, dtype=np.float64)

        cash_balance = (
            current.cash[policy_cash_slot, :]
            if policy_cash_slot >= 0
            else np.zeros(plan.rollout_count, dtype=np.float64)
        )
        required_sale = np.maximum(hard_demand - cash_balance, 0.0)
        post_required_cash = cash_balance + required_sale - hard_demand
        # Indexed amounts: per-rollout this-month values from compile-time amount arrays. Lets
        # the buffer track CPI when the wire emits a SeriesIndexedAmount; a `FixedAmount` (or
        # raw float) gives a constant vector with no work.
        buffer_trigger_values = _amount_values(
            plan,
            kind=int(plan.liquidity_policies.trigger_kind[policy]),
            fixed=float(plan.liquidity_policies.trigger_fixed[policy]),
            base=float(plan.liquidity_policies.trigger_base[policy]),
            series_index=int(plan.liquidity_policies.trigger_series[policy]),
            base_month=int(plan.liquidity_policies.trigger_base_month[policy]),
            adjustment_period=int(plan.liquidity_policies.trigger_period[policy]),
            month=month,
        )
        buffer_sale_values = _amount_values(
            plan,
            kind=int(plan.liquidity_policies.sale_kind[policy]),
            fixed=float(plan.liquidity_policies.sale_fixed[policy]),
            base=float(plan.liquidity_policies.sale_base[policy]),
            series_index=int(plan.liquidity_policies.sale_series[policy]),
            base_month=int(plan.liquidity_policies.sale_base_month[policy]),
            adjustment_period=int(plan.liquidity_policies.sale_period[policy]),
            month=month,
        )
        buffer_sale = np.where(
            (buffer_sale_values > 0.0) & (post_required_cash < buffer_trigger_values), buffer_sale_values, 0.0
        )
        remaining_target = np.where(active_rollout, required_sale + buffer_sale, 0.0)
        if not np.any((hard_demand > 0.0) | (remaining_target > 0.0)):
            continue

        for asset_idx in range(plan.liquidity_policies.assets.shape[1]):
            asset_code = int(plan.liquidity_policies.assets[policy, asset_idx])
            if asset_code < 0 or not np.any(remaining_target > 0.0):
                continue
            series_index = int(plan.liquidity_policies.asset_series[policy, asset_idx])
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

            available_value = current.lot_remaining[ordered_lots, :].sum(axis=0) * unit_price
            target_dollars = np.minimum(np.maximum(remaining_target, 0.0), available_value)
            target_dollars = np.where(valid_price & active_rollout, target_dollars, 0.0)
            if not np.any(target_dollars > 0.0):
                continue

            result = fifo_sell_dollars(
                lot_remaining=current.lot_remaining.T,
                ordered_lots=ordered_lots,
                target_dollars=target_dollars,
                unit_price=unit_price,
                cost_basis_per_unit=plan.lot_cost_basis_per_unit,
            )
            if result.oversell.any():
                raise ValueError(
                    "liquidity policy attempted to sell more than available lots: "
                    f"{plan.liquidity_policies.cause_id_prefixes[policy]}"
                )

            current.lot_remaining -= result.sold_units.T
            if policy_cash_slot >= 0:
                current.cash[policy_cash_slot, :] += result.total_proceeds
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
    for slot in range(plan.obligations.cause.shape[1]):
        if plan.obligations.cause[month, slot] < 0 or plan.obligations.source_kind[month, slot] < 0:
            continue
        source_kind = int(plan.obligations.source_kind[month, slot])
        source_index = int(plan.obligations.source_index[month, slot])
        amount = np.zeros(plan.rollout_count, dtype=np.float64)
        active = active_rollout.copy()

        if source_kind == SOURCE_CONFIGURED_OBLIGATION:
            amount = _amount_values(
                plan,
                kind=int(plan.obligations.amount_kind[month, slot]),
                fixed=float(plan.obligations.amount_fixed[month, slot]),
                base=float(plan.obligations.amount_base[month, slot]),
                series_index=int(plan.obligations.amount_series[month, slot]),
                base_month=int(plan.obligations.amount_base_month[month, slot]),
                adjustment_period=int(plan.obligations.amount_period[month, slot]),
                month=month,
            )
        elif source_kind == SOURCE_MORTGAGE_PAYMENT:
            liab = source_index
            prop = int(plan.liabilities.property_slot[liab])
            active &= (
                current.liability_active[liab, :]
                & (plan.properties.month[prop] < month)
                & (current.liability_principal[liab, :] > 0.0)
            )
            interest = current.liability_principal[liab, :] * float(plan.liabilities.annual_rate[liab]) / 12.0
            amount = np.minimum(
                current.liability_monthly_payment[liab, :], current.liability_principal[liab, :] + interest
            )
        elif source_kind == SOURCE_PROPERTY_TAX:
            prop = source_index
            active &= current.property_active[prop, :] & (plan.properties.month[prop] < month)
            rate = float(plan.obligations.amount_fixed[month, slot])
            if np.isnan(rate):
                rate = float(plan.properties.location_tax_rate[prop])
            ad_valorem_monthly = plan.properties.initial_assessed_value[prop] * rate / 12.0
            non_ad_valorem_monthly = plan.properties.special_assessment_annual_usd[prop] / 12.0
            amount = np.full(plan.rollout_count, ad_valorem_monthly + non_ad_valorem_monthly)
        elif source_kind == SOURCE_ESTIMATED_TAX:
            amount = np.full(plan.rollout_count, float(plan.tax.profile_prior_year_tax[source_index]) / 4.0)
        elif source_kind in (SOURCE_ESTIMATED_TAX_Q4, SOURCE_TAX_TRUE_UP):
            profile = source_index
            tax_year_end = (month // 12 - 1) * 12 + 11
            actual = _actual_tax_for_profile_year(plan, current, profile_index=profile, year_end_month=tax_year_end)
            safe_harbor = np.minimum(float(plan.tax.profile_prior_year_tax[profile]), actual)
            paid_before_q4 = float(plan.tax.profile_prior_year_tax[profile]) * 0.75
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
    tax_profile_count = plan.tax.profile_agent.shape[0]
    tax_payment_failed = np.zeros((tax_profile_count, plan.rollout_count), dtype=np.bool_)
    tax_settlement_candidate = np.zeros((tax_profile_count, plan.rollout_count), dtype=np.float64)
    tax_settlement_candidate_year_end = np.full((tax_profile_count, plan.rollout_count), NO_CODE, dtype=np.int64)

    for slot in range(active.shape[0]):
        active_slot = active[slot]
        if not active_slot.any():
            continue
        source_kind = int(plan.obligations.source_kind[month, slot])
        source_index = int(plan.obligations.source_index[month, slot])

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
            from_slot = int(plan.obligations.from_slot[month, slot])
            if from_slot >= 0:
                current.cash[from_slot, paid] -= amount[paid]
            to_slot = int(plan.obligations.to_slot[month, slot])
            if to_slot >= 0:
                current.cash[to_slot, paid] += amount[paid]
            if source_kind == SOURCE_MORTGAGE_PAYMENT:
                _apply_mortgage_payment(
                    plan, buffers, current, month=month, liability_slot=source_index, paid=paid, amount=amount
                )
            # Accumulate property-tax payments into the owner's per-profile YTD bucket so the
            # year-end federal SALT pass can read them. Only the owner-use share contributes
            # to SALT; the rented share routes to Schedule E via deduction_profile. The
            # compiler ties every property-tax obligation to a property_slot (kind==2 branch),
            # so the engine always reads runtime `current.property_rented_fraction` —
            # mid-horizon lifecycle events take effect without any compile-time fallback.
            property_tax_profile = int(plan.obligations.property_tax_profile[month, slot])
            property_slot = int(plan.obligations.property_slot[month, slot])
            if property_tax_profile >= 0:
                assert property_slot >= 0, "property-tax obligation must be tied to a property slot"
                rented_per_rollout = current.property_rented_fraction[property_slot, :]
                owner_per_rollout = 1.0 - rented_per_rollout
                current.property_tax_ytd[property_tax_profile, paid] += amount[paid] * owner_per_rollout[paid]
            # Schedule E deduction: decrement payer's ordinary_ytd. For property-tax
            # obligations the deductible_fraction comes from runtime state; for other
            # deductible obligations it comes from the compile-time value.
            deduction_profile = int(plan.obligations.deduction_profile[month, slot])
            if deduction_profile >= 0:
                if property_slot >= 0:
                    rented_per_rollout = current.property_rented_fraction[property_slot, :]
                    current.ordinary_ytd[deduction_profile, paid] -= amount[paid] * rented_per_rollout[paid]
                else:
                    deductible_fraction = float(plan.obligations.deductible_fraction[month, slot])
                    current.ordinary_ytd[deduction_profile, paid] -= amount[paid] * deductible_fraction

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
        agent = int(plan.obligations.agent[month, slot])
        from_slot = int(plan.obligations.from_slot[month, slot])
        group = (plan.obligations.agent[month] == agent) & (plan.obligations.from_slot[month] == from_slot)
        group_due = np.where(active[group], due[group], 0.0).sum(axis=0)
        available = current.cash[from_slot, :] if from_slot >= 0 else np.zeros(plan.rollout_count, dtype=np.float64)
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
    principal_before = current.liability_principal[liability_slot, :]
    interest = np.minimum(principal_before * float(plan.liabilities.annual_rate[liability_slot]) / 12.0, amount)
    principal = np.minimum(np.maximum(amount - interest, 0.0), principal_before)

    buffers.mortgage_payment_active[month, liability_slot, paid] = True
    buffers.mortgage_payment_interest[month, liability_slot, paid] = interest[paid]
    buffers.mortgage_payment_principal[month, liability_slot, paid] = principal[paid]
    buffers.mortgage_payment_total[month, liability_slot, paid] = amount[paid]
    current.liability_principal[liability_slot, paid] = np.maximum(0.0, principal_before[paid] - principal[paid])
    current.liability_interest_ytd[liability_slot, paid] += interest[paid]
    current.liability_principal_ytd[liability_slot, paid] += principal[paid]
    # Per-month rented share of interest, indexed by runtime property_rented_fraction so that
    # mid-horizon lifecycle transitions take effect immediately for MID + Schedule E.
    prop_slot = int(plan.liabilities.property_slot[liability_slot])
    if prop_slot >= 0:
        rented = current.property_rented_fraction[prop_slot, :]
        current.liability_rental_interest_ytd[liability_slot, paid] += interest[paid] * rented[paid]


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
        (plan.tax_liabilities.profile_index == profile_index) & (plan.tax_liabilities.year_end_month == year_end_month)
    )
    if slots.size == 0:
        return
    slot_amounts = current.tax_liability_amount[slots, :]
    eligible_amounts = np.where(current.tax_liability_active[slots, :], slot_amounts, 0.0)
    outstanding = eligible_amounts.sum(axis=0)
    settlement = np.where(active, settlement_amount, 0.0)
    weights = np.divide(
        eligible_amounts, outstanding[None, :], out=np.zeros_like(eligible_amounts), where=outstanding[None, :] > 0.0
    )
    settled = np.minimum(eligible_amounts, weights * settlement[None, :])
    current.tax_liability_amount[slots, :] = np.maximum(0.0, slot_amounts - settled)


def _actual_tax_for_profile_year(
    plan: CompiledSimulation, current: CurrentStateBuffers, *, profile_index: int, year_end_month: int
) -> np.ndarray:
    slots = np.flatnonzero(
        (plan.tax_liabilities.profile_index == profile_index) & (plan.tax_liabilities.year_end_month == year_end_month)
    )
    if slots.size == 0:
        return np.zeros(plan.rollout_count, dtype=np.float64)
    return np.where(current.tax_liability_active[slots, :], current.tax_liability_amount[slots, :], 0.0).sum(axis=0)


def _sale_unit_price(plan: CompiledSimulation, *, month: int, sale: int) -> np.ndarray:
    fixed_price = float(plan.sales.price_fixed[sale])
    if not np.isnan(fixed_price):
        return np.full(plan.rollout_count, fixed_price, dtype=np.float64)
    series_index = int(plan.sales.price_series[sale])
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
            current.capital_gain_active[profile, cls, active] = True
            current.capital_gain_ytd[profile, cls, :] += gains[:, lot]


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


def _codes_to_strings(plan: CompiledSimulation, codes: np.ndarray) -> np.ndarray:
    """Vectorize `_text` over an int-code array; preserves the input shape.

    Output dtype is `object` (str | None entries). Polars will infer pl.Utf8 on
    DataFrame construction; None becomes null."""

    flat = np.asarray(codes, dtype=np.int64).reshape(-1)
    out = np.empty(flat.size, dtype=object)
    strings = plan.strings
    for i in range(flat.size):
        code = int(flat[i])
        out[i] = strings[code] if code >= 0 else None
    return out.reshape(np.asarray(codes).shape)


def _r_first_view(state: np.ndarray) -> np.ndarray:
    """Move R (trailing axis per B0) to axis 1 so the decoders can keep using their
    (h1, r, count[, ...]) row-major iteration order over the resulting flat buffer."""

    return np.moveaxis(state, -1, 1)


def _state_axes(h1: int, r: int, s: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ravelled (month, rollout, slot) index columns for a state buffer of shape `(h1, r, s)`.

    Order is row-major over `(month, rollout, slot)` — matches the iteration order the
    old list-of-dicts decoders used so the resulting frame's row order is preserved.
    """

    months = np.broadcast_to(np.arange(h1, dtype=np.int64)[:, None, None], (h1, r, s)).ravel()
    rollouts = np.broadcast_to(np.arange(r, dtype=np.int64)[None, :, None], (h1, r, s)).ravel()
    slots = np.broadcast_to(np.arange(s, dtype=np.int64)[None, None, :], (h1, r, s)).ravel()
    return months, rollouts, slots


def _state_history_frame_from_columns(columns: dict[str, np.ndarray], spec: Any) -> pl.DataFrame:
    """Build a state-history frame from pre-built numpy column arrays. State-history specs
    don't carry `month_index` in their schema (the cross-section is one month wide); decode
    adds month_index in front of every column the spec declares, so this helper threads
    `rollout_index`, `month_index`, and the spec's remaining columns in the expected order.
    Empty input produces a correctly-typed empty frame."""

    state_schema = pl.Schema(
        {
            "rollout_index": pl.Int64(),
            "month_index": pl.Int64(),
            **{name: dtype for name, dtype in spec.schema.items() if name != "rollout_index"},
        }
    )
    n = next(iter(columns.values())).size
    if n == 0:
        return state_schema.to_frame()
    return pl.DataFrame(columns, schema=state_schema).select(list(state_schema.names()))


def _decode_cash(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    state = _r_first_view(buffers.cash_state)  # (H+1, r, s)
    h1, r, s = state.shape
    months, rollouts, slots = _state_axes(h1, r, s)
    agent_ids = _codes_to_strings(plan, plan.cash_agent_codes)
    account_ids = _codes_to_strings(plan, plan.cash_account_codes)
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts,
            "month_index": months,
            "agent_id": agent_ids[slots],
            "account_id": account_ids[slots],
            "balance_usd": state.reshape(-1),
        },
        CASH_BALANCES_FRAME,
    )


def _decode_asset_lots(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    state = _r_first_view(buffers.lot_state)  # (H+1, r, s)
    h1, r, s = state.shape
    months, rollouts, slots = _state_axes(h1, r, s)
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts,
            "month_index": months,
            "lot_id": _codes_to_strings(plan, plan.lot_id_codes)[slots],
            "agent_id": _codes_to_strings(plan, plan.lot_agent_codes)[slots],
            "account_id": _codes_to_strings(plan, plan.lot_account_codes)[slots],
            "asset_id": _codes_to_strings(plan, plan.lot_asset_codes)[slots],
            "purchase_month_index": plan.lot_purchase_month.astype(np.int64)[slots],
            "cost_basis_per_unit_usd": plan.lot_cost_basis_per_unit.astype(np.float64)[slots],
            "remaining_quantity": state.reshape(-1),
        },
        ASSET_LOT_FRAME,
    )


def _decode_ordinary_income(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    state = _r_first_view(buffers.ordinary_state)  # (H+1, r, p)
    h1, r, p = state.shape
    months, rollouts, profiles = _state_axes(h1, r, p)
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts,
            "month_index": months,
            "agent_id": _codes_to_strings(plan, plan.tax.profile_agent)[profiles],
            "ordinary_income_usd": state.reshape(-1),
        },
        ORDINARY_INCOME_YTD_FRAME,
    )


def _decode_capital_gains(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    # capital_gain_state: (H+1, r, p, 2). Last axis is (LTCG, STCG) per *_CAPITAL_GAIN_CODE.
    # Mask-filter keeps only `active_state[m, r, p, cls]` rows. The two `cls` codes happen to be
    # 0 and 1, with LTCG = LONG_TERM... = 0, STCG = SHORT_TERM... = 1, but iterate explicitly so
    # the classification column matches the legacy decoder's row order ((profile, ltcg, stcg)).
    state = _r_first_view(buffers.capital_gain_state)
    active = _r_first_view(buffers.capital_gain_active_state)
    h1, r, p, _c = state.shape
    months = np.broadcast_to(np.arange(h1, dtype=np.int64)[:, None, None, None], (h1, r, p, 2))
    rollouts = np.broadcast_to(np.arange(r, dtype=np.int64)[None, :, None, None], (h1, r, p, 2))
    profiles = np.broadcast_to(np.arange(p, dtype=np.int64)[None, None, :, None], (h1, r, p, 2))
    # Order class slots so LTCG (index LONG_TERM_CAPITAL_GAIN_CODE) comes first within each profile.
    cls_order = np.array([LONG_TERM_CAPITAL_GAIN_CODE, SHORT_TERM_CAPITAL_GAIN_CODE], dtype=np.int64)
    classification_labels = np.array(["ltcg", "stcg"], dtype=object)
    state_o = state[:, :, :, cls_order]
    active_o = active[:, :, :, cls_order]
    cls_labels = np.broadcast_to(classification_labels[None, None, None, :], (h1, r, p, 2))
    mask = active_o.reshape(-1)
    agent_ids = _codes_to_strings(plan, plan.capital_gain_agent_codes)
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts.reshape(-1)[mask],
            "month_index": months.reshape(-1)[mask],
            "agent_id": agent_ids[profiles.reshape(-1)[mask]],
            "classification": cls_labels.reshape(-1)[mask],
            "gain_usd": state_o.reshape(-1)[mask],
        },
        CAPITAL_GAINS_YTD_FRAME,
    )


def _decode_tax_liabilities(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    state = _r_first_view(buffers.tax_liability_state)  # (H+1, r, s)
    active = _r_first_view(buffers.tax_liability_active_state)
    h1, r, s = state.shape
    months, rollouts, slots = _state_axes(h1, r, s)
    mask = active.reshape(-1)
    profile_per_slot = plan.tax_liabilities.profile_index.astype(np.int64)
    link_per_slot = plan.tax_liabilities.link_index.astype(np.int64)
    agent_per_profile = _codes_to_strings(plan, plan.tax.profile_agent)
    juris_per_link = _codes_to_strings(plan, plan.tax.link_jurisdiction)
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts[mask],
            "month_index": months[mask],
            "agent_id": agent_per_profile[profile_per_slot[slots[mask]]],
            "jurisdiction_id": juris_per_link[link_per_slot[slots[mask]]],
            "tax_year_end_month": plan.tax_liabilities.year_end_month.astype(np.int64)[slots[mask]],
            "amount_owed_usd": state.reshape(-1)[mask],
        },
        TAX_LIABILITIES_FRAME,
    )


def _decode_property_state(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    basis = _r_first_view(buffers.property_basis_state)  # (H+1, r, p)
    active = _r_first_view(buffers.property_active_state)
    h1, r, p = basis.shape
    months, rollouts, props = _state_axes(h1, r, p)
    mask = active.reshape(-1)
    property_ids = _codes_to_strings(plan, plan.properties.id)
    location_ids = _codes_to_strings(plan, plan.properties.location_id)
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts[mask],
            "month_index": months[mask],
            "property_id": property_ids[props[mask]],
            "location_id": location_ids[props[mask]],
            "purchase_month_index": plan.properties.month.astype(np.int64)[props[mask]],
            "adjusted_basis_usd": basis.reshape(-1)[mask],
        },
        PROPERTY_STATE_FRAME,
    )


def _decode_property_stakes(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = _r_first_view(buffers.property_active_state)  # (H+1, r, p)
    h1, r, p = active.shape
    months, rollouts, props = _state_axes(h1, r, p)
    mask = active.reshape(-1)
    property_ids = _codes_to_strings(plan, plan.properties.id)
    buyer_ids = _codes_to_strings(plan, plan.properties.buyer_agent)
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts[mask],
            "month_index": months[mask],
            "property_id": property_ids[props[mask]],
            "agent_id": buyer_ids[props[mask]],
            "ownership_pct": buffers.property_ownership_state.reshape(-1)[mask],
            "contribution_used_usd": buffers.property_contribution_state.reshape(-1)[mask],
            "equity_ledger_usd": buffers.property_equity_state.reshape(-1)[mask],
        },
        PROPERTY_STAKE_FRAME,
    )


def _decode_liabilities(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    principal = _r_first_view(buffers.liability_principal_state)  # (H+1, R, n_liab)
    active = _r_first_view(buffers.liability_active_state)
    h1, r, n_liab = principal.shape
    months, rollouts, liabs = _state_axes(h1, r, n_liab)
    mask = active.reshape(-1)
    liability_ids = _codes_to_strings(plan, plan.liabilities.codes)
    agent_ids = _codes_to_strings(plan, plan.liabilities.agent)
    payment_account_ids = _codes_to_strings(plan, plan.liabilities.payment_account)
    counterparty_agent_ids = _codes_to_strings(plan, plan.liabilities.counterparty_agent)
    counterparty_account_ids = _codes_to_strings(plan, plan.liabilities.counterparty_account)
    property_ids_per_liab = _codes_to_strings(plan, plan.properties.id)[plan.liabilities.property_slot.astype(np.int64)]
    origination_per_liab = plan.properties.month.astype(np.int64)[plan.liabilities.property_slot.astype(np.int64)]
    return _state_history_frame_from_columns(
        {
            "rollout_index": rollouts[mask],
            "month_index": months[mask],
            "liability_id": liability_ids[liabs[mask]],
            "agent_id": agent_ids[liabs[mask]],
            "payment_account_id": payment_account_ids[liabs[mask]],
            "counterparty_agent_id": counterparty_agent_ids[liabs[mask]],
            "counterparty_account_id": counterparty_account_ids[liabs[mask]],
            "property_id": property_ids_per_liab[liabs[mask]],
            "principal_usd": principal.reshape(-1)[mask],
            "annual_interest_rate": plan.liabilities.annual_rate.astype(np.float64)[liabs[mask]],
            "term_months": plan.liabilities.term_months.astype(np.int64)[liabs[mask]],
            "origination_month_index": origination_per_liab[liabs[mask]],
            "monthly_payment_usd": buffers.liability_monthly_payment_state.reshape(-1)[mask],
            "interest_paid_ytd_usd": buffers.liability_interest_ytd_state.reshape(-1)[mask],
            "principal_paid_ytd_usd": buffers.liability_principal_ytd_state.reshape(-1)[mask],
        },
        LIABILITY_FRAME,
    )


def _decode_rollout_status_history(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    failed_state = buffers.rollout_failed_state  # (H+1, r) bool
    failed_month_state = buffers.rollout_failed_month_state.astype(np.int64)  # (H+1, r) int
    h1, r = failed_state.shape
    months = np.broadcast_to(np.arange(h1, dtype=np.int64)[:, None], (h1, r)).ravel()
    rollouts = np.broadcast_to(np.arange(r, dtype=np.int64)[None, :], (h1, r)).ravel()
    status = np.where(failed_state.reshape(-1), "failed_insufficient_cash", "active")
    failed_month_flat = failed_month_state.reshape(-1)
    # Polars rejects an object-dtype column for an Int64 schema; build the int|None list explicitly.
    # `h1*r` is small (≤ horizon × rollout_count) so the Python loop is fine.
    failed_month_col = [None if m < 0 else int(m) for m in failed_month_flat]
    return pl.DataFrame(
        {"rollout_index": rollouts, "month_index": months, "status": status, "failed_month": failed_month_col},
        schema={
            "rollout_index": pl.Int64(),
            "month_index": pl.Int64(),
            "status": pl.Utf8(),
            "failed_month": pl.Int64(),
        },
    )


def _decode_final_rollout_status(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    month = plan.horizon_months
    failed = buffers.rollout_failed_state[month]  # (r,) bool
    failed_month = buffers.rollout_failed_month_state[month].astype(np.int64)  # (r,) int
    r = failed.shape[0]
    if r == 0:
        return ROLLOUT_STATUS_FRAME.empty()
    rollouts = np.arange(r, dtype=np.int64)
    status = np.where(failed, "failed_insufficient_cash", "active")
    failed_month_col = [None if m < 0 else int(m) for m in failed_month]
    return ROLLOUT_STATUS_FRAME.normalize(
        pl.DataFrame(
            {"rollout_index": rollouts, "status": status, "failed_month": failed_month_col},
            schema={"rollout_index": pl.Int64(), "status": pl.Utf8(), "failed_month": pl.Int64()},
        )
    )


def _decode_events(plan: CompiledSimulation, buffers: SimulationBuffers) -> EventLog:
    transfer_frames: list[pl.DataFrame] = []
    lot_frames: list[pl.DataFrame] = []
    transfer_frames.append(_decode_transfers(plan, buffers))
    property_purchases_frame, property_transfer_frame = _decode_property_purchases(plan, buffers)
    transfer_frames.append(property_transfer_frame)
    lot_frames.append(_decode_sched_dispositions(plan, buffers))
    lot_frames.append(_decode_liquidity_dispositions(plan, buffers))
    tax_accruals_frame, tax_breakdowns_frame = _decode_tax_accruals(plan, buffers)
    obligation_accruals_frame, obligation_settlements_frame, obligation_transfer_frame, failure_frame = (
        _decode_obligations(plan, buffers)
    )
    transfer_frames.append(obligation_transfer_frame)
    set_rented_fraction_frame, capital_improvement_frame, property_sale_frame = _decode_lifecycle_events(plan, buffers)
    return EventLog.from_frames(
        {
            "transfers": EVENT_FRAMES.transfers.concat(transfer_frames),
            "lot_dispositions": EVENT_FRAMES.lot_dispositions.concat(lot_frames),
            "tax_accruals": tax_accruals_frame,
            "tax_breakdowns": tax_breakdowns_frame,
            "tax_settlements": _decode_tax_settlements(plan, buffers),
            "obligation_accruals": obligation_accruals_frame,
            "obligation_settlements": obligation_settlements_frame,
            "property_purchases": property_purchases_frame,
            "mortgage_originations": _decode_mortgage_originations(plan, buffers),
            "mortgage_payments": _decode_mortgage_payments(plan, buffers),
            "rollout_failures": failure_frame,
            "set_rented_fraction_events": set_rented_fraction_frame,
            "capital_improvement_events": capital_improvement_frame,
            "property_sale_events": property_sale_frame,
        }
    )


def _decode_lifecycle_events(
    plan: CompiledSimulation, buffers: SimulationBuffers
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Decode `buffers.lifecycle` into per-kind polars frames.

    Each lifecycle event is fanned out to one row per active (rollout, event) pair using
    `buffers.lifecycle_fired`. The compile-time `lifecycle_event_kind` selects which schema
    each event belongs to; sale events additionally pull per-rollout dollar figures from the
    `sale_*` arrays.
    """

    event_count = int(plan.lifecycle_events.month.shape[0])
    if event_count == 0:
        return (
            EVENT_FRAMES.set_rented_fraction_events.empty(),
            EVENT_FRAMES.capital_improvement_events.empty(),
            EVENT_FRAMES.property_sale_events.empty(),
        )
    fired = buffers.lifecycle_fired[:event_count]  # (E, R)
    events_idx, rollouts = np.argwhere(fired).T if fired.any() else (np.array([], dtype=np.int64),) * 2
    if events_idx.size == 0:
        return (
            EVENT_FRAMES.set_rented_fraction_events.empty(),
            EVENT_FRAMES.capital_improvement_events.empty(),
            EVENT_FRAMES.property_sale_events.empty(),
        )
    months = plan.lifecycle_events.month.astype(np.int64)[events_idx]
    property_slots = plan.lifecycle_events.property_slot.astype(np.int64)[events_idx]
    property_ids = _codes_to_strings(plan, plan.properties.id)[property_slots]
    kinds = plan.lifecycle_events.kind.astype(np.int64)[events_idx]
    fraction_mask = kinds == LIFECYCLE_KIND_FRACTION
    capital_mask = kinds == LIFECYCLE_KIND_CAPITAL_IMPROVEMENT
    sale_mask = kinds == LIFECYCLE_KIND_SALE

    set_rented_fraction_frame = _frame_from_columns(
        EVENT_FRAMES.set_rented_fraction_events,
        rollout_index=rollouts[fraction_mask],
        month_index=months[fraction_mask],
        property_id=property_ids[fraction_mask],
        rented_fraction=plan.lifecycle_events.rented_fraction.astype(np.float64)[events_idx[fraction_mask]],
    )
    capital_improvement_frame = _frame_from_columns(
        EVENT_FRAMES.capital_improvement_events,
        rollout_index=rollouts[capital_mask],
        month_index=months[capital_mask],
        property_id=property_ids[capital_mask],
        amount_usd=plan.lifecycle_events.amount.astype(np.float64)[events_idx[capital_mask]],
        description=np.full(int(capital_mask.sum()), "", dtype=object),
    )
    property_sale_frame = _frame_from_columns(
        EVENT_FRAMES.property_sale_events,
        rollout_index=rollouts[sale_mask],
        month_index=months[sale_mask],
        property_id=property_ids[sale_mask],
        gross_proceeds_usd=buffers.lifecycle_sale_gross_proceeds[events_idx[sale_mask], rollouts[sale_mask]],
        mortgage_payoff_usd=buffers.lifecycle_sale_mortgage_payoff[events_idx[sale_mask], rollouts[sale_mask]],
        net_cash_to_owner_usd=buffers.lifecycle_sale_net_cash[events_idx[sale_mask], rollouts[sale_mask]],
        realized_gain_usd=buffers.lifecycle_sale_realized_gain[events_idx[sale_mask], rollouts[sale_mask]],
        depreciation_recapture_usd=buffers.lifecycle_sale_recapture[events_idx[sale_mask], rollouts[sale_mask]],
        section_121_exclusion_usd=buffers.lifecycle_sale_section_121_exclusion[
            events_idx[sale_mask], rollouts[sale_mask]
        ],
        long_term_capital_gain_usd=buffers.lifecycle_sale_long_term_gain[events_idx[sale_mask], rollouts[sale_mask]],
    )
    return set_rented_fraction_frame, capital_improvement_frame, property_sale_frame


def _decode_transfers(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.transfer_active  # (M, S, R)
    months, slots, rollouts = np.argwhere(active).T if active.any() else (np.array([], dtype=np.int64),) * 3
    cause_ids = _codes_to_strings(plan, plan.transfers.cause)[months, slots]
    from_agents = _codes_to_strings(plan, plan.transfers.from_agent)[months, slots]
    from_accounts = _codes_to_strings(plan, plan.transfers.from_account)[months, slots]
    to_agents = _codes_to_strings(plan, plan.transfers.to_agent)[months, slots]
    to_accounts = _codes_to_strings(plan, plan.transfers.to_account)[months, slots]
    amounts = buffers.transfer_amount[months, slots, rollouts]
    income_categories = np.where(plan.transfers.income_profile[months, slots] >= 0, "ordinary", None).astype(object)
    return _frame_from_columns(
        EVENT_FRAMES.transfers,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        from_agent_id=from_agents,
        from_account_id=from_accounts,
        to_agent_id=to_agents,
        to_account_id=to_accounts,
        amount_usd=amounts,
        income_category=income_categories,
    )


def _decode_property_purchases(
    plan: CompiledSimulation, buffers: SimulationBuffers
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Returns (property_purchases_frame, derived_transfers_frame).

    The transfers frame is the subset of purchases whose `property_transfer_active` flag is
    set — the buyer-cash transfer that goes alongside the purchase event.
    """

    active = buffers.property_purchase_active  # (M, P, R)
    if active.any():
        months, props, rollouts = np.argwhere(active).T
    else:
        months = props = rollouts = np.array([], dtype=np.int64)
    cause_ids = _codes_to_strings(plan, plan.properties.cause)[months, props]
    property_ids = _codes_to_strings(plan, plan.properties.id)[props]
    location_ids = _codes_to_strings(plan, plan.properties.location_id)[props]
    buyer_agents = _codes_to_strings(plan, plan.properties.buyer_agent)[props]
    buyer_accounts = _codes_to_strings(plan, plan.properties.buyer_account)[props]
    seller_agents = _codes_to_strings(plan, plan.properties.seller_agent)[props]
    seller_accounts = _codes_to_strings(plan, plan.properties.seller_account)[props]
    purchases = _frame_from_columns(
        EVENT_FRAMES.property_purchases,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        property_id=property_ids,
        location_id=location_ids,
        buyer_agent_id=buyer_agents,
        purchase_price_usd=plan.properties.purchase_price.astype(np.float64)[props],
        closing_cost_usd=plan.properties.closing_cost.astype(np.float64)[props],
        adjusted_basis_usd=plan.properties.adjusted_basis.astype(np.float64)[props],
        ownership_pct=plan.properties.ownership.astype(np.float64)[props],
        stake_contribution_usd=plan.properties.stake_contribution.astype(np.float64)[props],
        equity_ledger_usd=plan.properties.equity_ledger.astype(np.float64)[props],
    )
    # Derived buyer-cash transfers: subset where `property_transfer_active` also holds.
    transfer_mask = buffers.property_transfer_active[months, props, rollouts]
    if transfer_mask.any():
        m_t = months[transfer_mask]
        p_t = props[transfer_mask]
        r_t = rollouts[transfer_mask]
        cause_t = np.array([f"{c}_buyer_cash" for c in cause_ids[transfer_mask]], dtype=object)
        transfers = _frame_from_columns(
            EVENT_FRAMES.transfers,
            rollout_index=r_t,
            month_index=m_t,
            cause_id=cause_t,
            from_agent_id=buyer_agents[transfer_mask],
            from_account_id=buyer_accounts[transfer_mask],
            to_agent_id=seller_agents[transfer_mask],
            to_account_id=seller_accounts[transfer_mask],
            amount_usd=plan.properties.stake_contribution.astype(np.float64)[p_t],
            income_category=np.full(p_t.size, None, dtype=object),
        )
    else:
        transfers = EVENT_FRAMES.transfers.empty()
    return purchases, transfers


def _decode_sched_dispositions(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.sched_disp_active  # (M, sale, lot, R)
    if active.any():
        months, sales, lots, rollouts = np.argwhere(active).T
    else:
        months = sales = lots = rollouts = np.array([], dtype=np.int64)
    cause_ids = _codes_to_strings(plan, plan.sales.cause)[months, sales]
    return _lot_disposition_frame(
        plan=plan,
        rollouts=rollouts,
        months=months,
        cause_ids=cause_ids,
        agent_codes=plan.sales.agent[sales],
        source_account_codes=plan.sales.source_account[sales],
        asset_codes=plan.sales.asset[sales],
        lots=lots,
        units=buffers.sched_disp_units[months, sales, lots, rollouts],
        basis=buffers.sched_disp_basis[months, sales, lots, rollouts],
        proceeds=buffers.sched_disp_proceeds[months, sales, lots, rollouts],
        proceeds_account_codes=plan.sales.proceeds_account[sales],
    )


def _decode_liquidity_dispositions(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.liq_disp_active  # (M, policy, asset_idx, lot, R)
    # Pre-filter inactive asset slots (asset_code < 0). The plan's liquidity_policy_asset_codes
    # is (policy, asset_idx); a negative entry means that asset slot isn't used by the policy.
    asset_valid = plan.liquidity_policies.assets >= 0  # (policy, asset_idx)
    # Broadcast valid mask to active's shape and AND it in.
    valid_full = asset_valid[None, :, :, None, None]  # (1, policy, asset_idx, 1, 1)
    active = active & valid_full
    if active.any():
        months, policies, asset_idxs, lots, rollouts = np.argwhere(active).T
    else:
        months = policies = asset_idxs = lots = rollouts = np.array([], dtype=np.int64)
    asset_codes = plan.liquidity_policies.assets[policies, asset_idxs]
    # Per-event cause_id is "{policy_prefix}_m{month}_{asset_name}". O(N) Python comp over
    # the gathered events, not the dense iteration space.
    asset_names = _codes_to_strings(plan, plan.liquidity_policies.assets)[policies, asset_idxs]
    prefixes_per_event = np.array(plan.liquidity_policies.cause_id_prefixes, dtype=object)[policies]
    cause_ids = np.array(
        [f"{p}_m{m}_{a}" for p, m, a in zip(prefixes_per_event, months, asset_names, strict=True)], dtype=object
    )
    return _lot_disposition_frame(
        plan=plan,
        rollouts=rollouts,
        months=months,
        cause_ids=cause_ids,
        agent_codes=plan.liquidity_policies.agent[policies],
        source_account_codes=plan.liquidity_policies.account[policies],
        asset_codes=asset_codes,
        lots=lots,
        units=buffers.liq_disp_units[months, policies, asset_idxs, lots, rollouts],
        basis=buffers.liq_disp_basis[months, policies, asset_idxs, lots, rollouts],
        proceeds=buffers.liq_disp_proceeds[months, policies, asset_idxs, lots, rollouts],
        proceeds_account_codes=plan.liquidity_policies.account[policies],
    )


def _lot_disposition_frame(
    *,
    plan: CompiledSimulation,
    rollouts: np.ndarray,
    months: np.ndarray,
    cause_ids: np.ndarray,
    agent_codes: np.ndarray,
    source_account_codes: np.ndarray,
    asset_codes: np.ndarray,
    lots: np.ndarray,
    units: np.ndarray,
    basis: np.ndarray,
    proceeds: np.ndarray,
    proceeds_account_codes: np.ndarray,
) -> pl.DataFrame:
    return _frame_from_columns(
        EVENT_FRAMES.lot_dispositions,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=_codes_to_strings(plan, agent_codes),
        source_account_id=_codes_to_strings(plan, source_account_codes),
        asset_id=_codes_to_strings(plan, asset_codes),
        lot_id=_codes_to_strings(plan, plan.lot_id_codes)[lots],
        purchase_month_index=plan.lot_purchase_month.astype(np.int64)[lots],
        units_sold=units,
        cost_basis_consumed_usd=basis,
        proceeds_usd=proceeds,
        proceeds_account_id=_codes_to_strings(plan, proceeds_account_codes),
    )


def _decode_tax_accruals(plan: CompiledSimulation, buffers: SimulationBuffers) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Returns (tax_accruals_frame, tax_breakdowns_frame). Same active mask, two output frames."""

    active = buffers.tax_accrual_active  # (M, link, R)
    if active.any():
        months, links, rollouts = np.argwhere(active).T
    else:
        months = links = rollouts = np.array([], dtype=np.int64)
    profiles = plan.tax.link_profile.astype(np.int64)[links]
    agent_ids = _codes_to_strings(plan, plan.tax.profile_agent)[profiles]
    jurisdiction_ids = _codes_to_strings(plan, plan.tax.link_jurisdiction)[links]
    # cause_id is f"{agent_id}_{jurisdiction_id}_year_end_accrual_m{month}".
    cause_ids = np.array(
        [f"{a}_{j}_year_end_accrual_m{m}" for a, j, m in zip(agent_ids, jurisdiction_ids, months, strict=True)],
        dtype=object,
    )
    totals = buffers.tax_accrual_amount[months, links, rollouts]
    accruals = _frame_from_columns(
        EVENT_FRAMES.tax_accruals,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=agent_ids,
        jurisdiction_id=jurisdiction_ids,
        tax_year_end_month=months,
        amount_usd=totals,
    )
    breakdowns = _frame_from_columns(
        EVENT_FRAMES.tax_breakdowns,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=agent_ids,
        jurisdiction_id=jurisdiction_ids,
        tax_year_end_month=months,
        ordinary_income_usd=buffers.tax_breakdown_ordinary[months, links, rollouts],
        ltcg_usd=buffers.tax_breakdown_ltcg[months, links, rollouts],
        stcg_usd=buffers.tax_breakdown_stcg[months, links, rollouts],
        standard_deduction_usd=plan.tax.link_standard_deduction.astype(np.float64)[links],
        mortgage_interest_deduction_usd=buffers.tax_breakdown_mortgage_interest_deduction[months, links, rollouts],
        salt_deduction_usd=buffers.tax_breakdown_salt_deduction[months, links, rollouts],
        itemized_deduction_usd=buffers.tax_breakdown_itemized_deduction[months, links, rollouts],
        ordinary_taxable_usd=buffers.tax_breakdown_ordinary_taxable[months, links, rollouts],
        capital_gain_taxable_usd=buffers.tax_breakdown_capital_taxable[months, links, rollouts],
        ordinary_tax_usd=buffers.tax_breakdown_ordinary_tax[months, links, rollouts],
        capital_gain_tax_usd=buffers.tax_breakdown_capital_tax[months, links, rollouts],
        total_tax_usd=totals,
    )
    return accruals, breakdowns


def _decode_obligations(
    plan: CompiledSimulation, buffers: SimulationBuffers
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Returns (accruals, settlements, derived_transfers, failures).

    Base mask is `obligation_active`; the transfer-row subset gates on
    `obligation_paid > 0`, the failure-row subset on `obligation_failure_active`.
    """

    active = buffers.obligation_active  # (M, S, R)
    if active.any():
        months, slots, rollouts = np.argwhere(active).T
    else:
        months = slots = rollouts = np.array([], dtype=np.int64)
    cause_ids = _codes_to_strings(plan, plan.obligations.cause)[months, slots]
    obligation_ids = _codes_to_strings(plan, plan.obligations.id)[months, slots]
    obligation_types = _codes_to_strings(plan, plan.obligations.type)[months, slots]
    agent_ids = _codes_to_strings(plan, plan.obligations.agent)[months, slots]
    from_account_ids = _codes_to_strings(plan, plan.obligations.from_account)[months, slots]
    to_agent_ids = _codes_to_strings(plan, plan.obligations.to_agent)[months, slots]
    to_account_ids = _codes_to_strings(plan, plan.obligations.to_account)[months, slots]
    amount_due = buffers.obligation_due[months, slots, rollouts]
    amount_paid = buffers.obligation_paid[months, slots, rollouts]
    shortfall = buffers.obligation_shortfall[months, slots, rollouts]
    attempt_policy = buffers.obligation_attempt_policy[months, slots, rollouts]
    attempted_sources_per_event = _attempted_sources_for_policy_indices(plan, attempt_policy)

    accruals = _frame_from_columns(
        EVENT_FRAMES.obligation_accruals,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        obligation_id=obligation_ids,
        obligation_type=obligation_types,
        agent_id=agent_ids,
        from_account_id=from_account_ids,
        to_agent_id=to_agent_ids,
        to_account_id=to_account_ids,
        amount_due_usd=amount_due,
    )
    settlements = _frame_from_columns(
        EVENT_FRAMES.obligation_settlements,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        obligation_id=obligation_ids,
        obligation_type=obligation_types,
        agent_id=agent_ids,
        from_account_id=from_account_ids,
        amount_due_usd=amount_due,
        amount_paid_usd=amount_paid,
        shortfall_usd=shortfall,
        attempted_funding_sources=attempted_sources_per_event,
    )
    # Subset 1: obligations with paid > 0 emit a derived transfer row.
    paid_mask = amount_paid > 0
    if paid_mask.any():
        transfers = _frame_from_columns(
            EVENT_FRAMES.transfers,
            rollout_index=rollouts[paid_mask],
            month_index=months[paid_mask],
            cause_id=cause_ids[paid_mask],
            from_agent_id=agent_ids[paid_mask],
            from_account_id=from_account_ids[paid_mask],
            to_agent_id=to_agent_ids[paid_mask],
            to_account_id=to_account_ids[paid_mask],
            amount_usd=amount_paid[paid_mask],
            income_category=np.full(int(paid_mask.sum()), None, dtype=object),
        )
    else:
        transfers = EVENT_FRAMES.transfers.empty()
    # Subset 2: obligations whose failure flag fired emit a failure row.
    failure_mask = buffers.obligation_failure_active[months, slots, rollouts]
    if failure_mask.any():
        failure_cause_ids = np.array([f"{oid}_failure" for oid in obligation_ids[failure_mask]], dtype=object)
        failures = _frame_from_columns(
            EVENT_FRAMES.rollout_failures,
            rollout_index=rollouts[failure_mask],
            month_index=months[failure_mask],
            cause_id=failure_cause_ids,
            agent_id=agent_ids[failure_mask],
            deficit_usd=shortfall[failure_mask],
            obligation_id=obligation_ids[failure_mask],
            obligation_type=obligation_types[failure_mask],
            amount_due_usd=amount_due[failure_mask],
            amount_paid_usd=amount_paid[failure_mask],
            shortfall_usd=shortfall[failure_mask],
            attempted_funding_sources=attempted_sources_per_event[failure_mask],
        )
    else:
        failures = EVENT_FRAMES.rollout_failures.empty()
    return accruals, settlements, transfers, failures


def _attempted_sources_for_policy_indices(plan: CompiledSimulation, attempt_policy: np.ndarray) -> np.ndarray:
    """Map a per-event `attempt_policy` int array to the matching joined-asset-names strings.

    `-1` (no attempting policy) maps to `""`. The result is an object-dtype array of strings,
    shape matching the input.
    """

    policy_count = plan.liquidity_policies.assets.shape[0]
    lookup = np.empty(policy_count + 1, dtype=object)
    lookup[0] = ""
    for policy in range(policy_count):
        lookup[policy + 1] = _attempted_sources(plan, policy)
    # Shift attempt_policy by +1 so -1 -> 0 (empty string).
    return lookup[attempt_policy.astype(np.int64) + 1]


def _decode_mortgage_originations(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.mortgage_origination_active  # (M, liab, R)
    if active.any():
        months, liabs, rollouts = np.argwhere(active).T
    else:
        months = liabs = rollouts = np.array([], dtype=np.int64)
    props = plan.liabilities.property_slot.astype(np.int64)[liabs]
    cause_codes_per_event = plan.properties.cause[months, props]
    cause_text = _codes_to_strings(plan, cause_codes_per_event)
    cause_ids = np.array([f"{c}_mortgage_origination" for c in cause_text], dtype=object)
    return _frame_from_columns(
        EVENT_FRAMES.mortgage_originations,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        liability_id=_codes_to_strings(plan, plan.liabilities.codes)[liabs],
        agent_id=_codes_to_strings(plan, plan.liabilities.agent)[liabs],
        payment_account_id=_codes_to_strings(plan, plan.liabilities.payment_account)[liabs],
        counterparty_agent_id=_codes_to_strings(plan, plan.liabilities.counterparty_agent)[liabs],
        counterparty_account_id=_codes_to_strings(plan, plan.liabilities.counterparty_account)[liabs],
        property_id=_codes_to_strings(plan, plan.properties.id)[props],
        principal_usd=plan.liabilities.principal.astype(np.float64)[liabs],
        annual_interest_rate=plan.liabilities.annual_rate.astype(np.float64)[liabs],
        term_months=plan.liabilities.term_months.astype(np.int64)[liabs],
        monthly_payment_usd=plan.liabilities.monthly_payment.astype(np.float64)[liabs],
    )


def _decode_mortgage_payments(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.mortgage_payment_active  # (M, liab, R)
    if active.any():
        months, liabs, rollouts = np.argwhere(active).T
    else:
        months = liabs = rollouts = np.array([], dtype=np.int64)
    props = plan.liabilities.property_slot.astype(np.int64)[liabs]
    liability_ids = _codes_to_strings(plan, plan.liabilities.codes)[liabs]
    cause_ids = np.array([f"{lid}_payment_m{m}" for lid, m in zip(liability_ids, months, strict=True)], dtype=object)
    return _frame_from_columns(
        EVENT_FRAMES.mortgage_payments,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        liability_id=liability_ids,
        agent_id=_codes_to_strings(plan, plan.liabilities.agent)[liabs],
        counterparty_agent_id=_codes_to_strings(plan, plan.liabilities.counterparty_agent)[liabs],
        property_id=_codes_to_strings(plan, plan.properties.id)[props],
        from_account_id=_codes_to_strings(plan, plan.liabilities.payment_account)[liabs],
        to_account_id=_codes_to_strings(plan, plan.liabilities.counterparty_account)[liabs],
        interest_usd=buffers.mortgage_payment_interest[months, liabs, rollouts],
        principal_usd=buffers.mortgage_payment_principal[months, liabs, rollouts],
        total_payment_usd=buffers.mortgage_payment_total[months, liabs, rollouts],
    )


def _decode_tax_settlements(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.tax_settlement_active  # (M, profile, R)
    if active.any():
        months, profiles, rollouts = np.argwhere(active).T
    else:
        months = profiles = rollouts = np.array([], dtype=np.int64)
    agent_ids = _codes_to_strings(plan, plan.tax.profile_agent)[profiles]
    year_end = buffers.tax_settlement_year_end_month[months, profiles, rollouts].astype(np.int64)
    tax_years = (year_end - 11) // 12
    cause_ids = np.array([f"{a}_tax_settlement_y{y}" for a, y in zip(agent_ids, tax_years, strict=True)], dtype=object)
    return _frame_from_columns(
        EVENT_FRAMES.tax_settlements,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=agent_ids,
        tax_year_end_month=year_end,
        amount_usd=buffers.tax_settlement_amount[months, profiles, rollouts],
    )


def _frame_from_columns(spec: Any, **columns: np.ndarray) -> pl.DataFrame:
    """Materialize an event frame from numpy column arrays. Empty input produces a
    correctly-typed empty frame matching the spec's schema. Polars cast/infer is driven by
    `spec.schema` so object-dtype numpy arrays of Python strings become `pl.Utf8` (rather
    than `pl.Object`, which breaks downstream concat between dense and empty frames)."""

    n = next(iter(columns.values())).size
    if n == 0:
        return spec.empty()
    return pl.DataFrame(columns, schema=spec.schema).select(spec.schema.names())


def _attempted_sources(plan: CompiledSimulation, policy: int) -> str:
    """Per-policy joined-asset-names string used in obligation settlement / failure rows.

    Called once per policy at decode time (small fixed count) to populate the lookup table
    `_attempted_sources_for_policy_indices` uses to gather per-event strings."""

    if policy < 0:
        return ""
    return ",".join(
        _text(plan, asset_code) or ""
        for asset_code in plan.liquidity_policies.assets[policy].tolist()
        if asset_code >= 0
    )
