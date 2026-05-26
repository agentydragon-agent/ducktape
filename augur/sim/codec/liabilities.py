"""Liability domain decoders: principal/payment state, mortgage origination + payment
events. The compile-side twin is `LiabilityCompileOutput` + `_compile_liabilities` in
`augur.sim.compiler`."""

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
from augur.sim.state import LIABILITY_FRAME


def decode_liabilities(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    principal = r_first_view(buffers.liability_principal_state)  # (H+1, R, n_liab)
    active = r_first_view(buffers.liability_active_state)
    h1, r, n_liab = principal.shape
    months, rollouts, liabs = state_axes(h1, r, n_liab)
    mask = active.reshape(-1)
    liability_ids = codes_to_strings(plan, plan.liabilities.codes)
    agent_ids = codes_to_strings(plan, plan.liabilities.agent)
    payment_account_ids = codes_to_strings(plan, plan.liabilities.payment_account)
    counterparty_agent_ids = codes_to_strings(plan, plan.liabilities.counterparty_agent)
    counterparty_account_ids = codes_to_strings(plan, plan.liabilities.counterparty_account)
    property_ids_per_liab = codes_to_strings(plan, plan.properties.id)[plan.liabilities.property_slot.astype(np.int64)]
    origination_per_liab = plan.properties.month.astype(np.int64)[plan.liabilities.property_slot.astype(np.int64)]
    return state_history_frame_from_columns(
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


def decode_mortgage_originations(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.mortgage_origination_active  # (M, liab, R)
    if active.any():
        months, liabs, rollouts = np.argwhere(active).T
    else:
        months = liabs = rollouts = np.array([], dtype=np.int64)
    props = plan.liabilities.property_slot.astype(np.int64)[liabs]
    cause_codes_per_event = plan.properties.cause[months, props]
    cause_text = codes_to_strings(plan, cause_codes_per_event)
    cause_ids = np.array([f"{c}_mortgage_origination" for c in cause_text], dtype=object)
    return frame_from_columns(
        EVENT_FRAMES.mortgage_originations,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        liability_id=codes_to_strings(plan, plan.liabilities.codes)[liabs],
        agent_id=codes_to_strings(plan, plan.liabilities.agent)[liabs],
        payment_account_id=codes_to_strings(plan, plan.liabilities.payment_account)[liabs],
        counterparty_agent_id=codes_to_strings(plan, plan.liabilities.counterparty_agent)[liabs],
        counterparty_account_id=codes_to_strings(plan, plan.liabilities.counterparty_account)[liabs],
        property_id=codes_to_strings(plan, plan.properties.id)[props],
        principal_usd=plan.liabilities.principal.astype(np.float64)[liabs],
        annual_interest_rate=plan.liabilities.annual_rate.astype(np.float64)[liabs],
        term_months=plan.liabilities.term_months.astype(np.int64)[liabs],
        monthly_payment_usd=plan.liabilities.monthly_payment.astype(np.float64)[liabs],
    )


def decode_mortgage_payments(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.mortgage_payment_active  # (M, liab, R)
    if active.any():
        months, liabs, rollouts = np.argwhere(active).T
    else:
        months = liabs = rollouts = np.array([], dtype=np.int64)
    props = plan.liabilities.property_slot.astype(np.int64)[liabs]
    liability_ids = codes_to_strings(plan, plan.liabilities.codes)[liabs]
    cause_ids = np.array([f"{lid}_payment_m{m}" for lid, m in zip(liability_ids, months, strict=True)], dtype=object)
    return frame_from_columns(
        EVENT_FRAMES.mortgage_payments,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        liability_id=liability_ids,
        agent_id=codes_to_strings(plan, plan.liabilities.agent)[liabs],
        counterparty_agent_id=codes_to_strings(plan, plan.liabilities.counterparty_agent)[liabs],
        property_id=codes_to_strings(plan, plan.properties.id)[props],
        from_account_id=codes_to_strings(plan, plan.liabilities.payment_account)[liabs],
        to_account_id=codes_to_strings(plan, plan.liabilities.counterparty_account)[liabs],
        interest_usd=buffers.mortgage_payment_interest[months, liabs, rollouts],
        principal_usd=buffers.mortgage_payment_principal[months, liabs, rollouts],
        total_payment_usd=buffers.mortgage_payment_total[months, liabs, rollouts],
    )
