"""Asset domain decoders: cash balances, lot inventory, and lot dispositions.
The compile-side twins live in `_compile_lots`, `_compile_cash`, `_compile_sales`,
and `_compile_liquidity_policies` in `augur.sim.compiler`."""

from __future__ import annotations

import numpy as np
import polars as pl

from augur.sim.buffers import SimulationBuffers
from augur.sim.codec.helpers import (
    codes_to_strings,
    frame_from_columns,
    r_first_view,
    state_axes,
    state_history_frame_from_columns,
)
from augur.sim.compiler import CompiledSimulation
from augur.sim.events import EVENT_FRAMES
from augur.sim.state import ASSET_LOT_FRAME, CASH_BALANCES_FRAME


def decode_cash(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    state = r_first_view(buffers.cash_state)  # (H+1, r, s)
    h1, r, s = state.shape
    months, rollouts, slots = state_axes(h1, r, s)
    agent_ids = codes_to_strings(plan, plan.cash_agent_codes)
    account_ids = codes_to_strings(plan, plan.cash_account_codes)
    return state_history_frame_from_columns(
        {
            "rollout_index": rollouts,
            "month_index": months,
            "agent_id": agent_ids[slots],
            "account_id": account_ids[slots],
            "balance_usd": state.reshape(-1),
        },
        CASH_BALANCES_FRAME,
    )


def decode_asset_lots(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    state = r_first_view(buffers.lot_state)  # (H+1, r, s)
    h1, r, s = state.shape
    months, rollouts, slots = state_axes(h1, r, s)
    return state_history_frame_from_columns(
        {
            "rollout_index": rollouts,
            "month_index": months,
            "lot_id": codes_to_strings(plan, plan.lot_id_codes)[slots],
            "agent_id": codes_to_strings(plan, plan.lot_agent_codes)[slots],
            "account_id": codes_to_strings(plan, plan.lot_account_codes)[slots],
            "asset_id": codes_to_strings(plan, plan.lot_asset_codes)[slots],
            "purchase_month_index": plan.lot_purchase_month.astype(np.int64)[slots],
            "cost_basis_per_unit_usd": plan.lot_cost_basis_per_unit.astype(np.float64)[slots],
            "remaining_quantity": state.reshape(-1),
        },
        ASSET_LOT_FRAME,
    )


def decode_sched_dispositions(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.sched_disp_active  # (M, sale, lot, R)
    if active.any():
        months, sales, lots, rollouts = np.argwhere(active).T
    else:
        months = sales = lots = rollouts = np.array([], dtype=np.int64)
    cause_ids = codes_to_strings(plan, plan.sales.cause)[months, sales]
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


def decode_liquidity_dispositions(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
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
    asset_names = codes_to_strings(plan, plan.liquidity_policies.assets)[policies, asset_idxs]
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
    return frame_from_columns(
        EVENT_FRAMES.lot_dispositions,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=codes_to_strings(plan, agent_codes),
        source_account_id=codes_to_strings(plan, source_account_codes),
        asset_id=codes_to_strings(plan, asset_codes),
        lot_id=codes_to_strings(plan, plan.lot_id_codes)[lots],
        purchase_month_index=plan.lot_purchase_month.astype(np.int64)[lots],
        units_sold=units,
        cost_basis_consumed_usd=basis,
        proceeds_usd=proceeds,
        proceeds_account_id=codes_to_strings(plan, proceeds_account_codes),
    )
