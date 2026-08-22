"""Property domain decoders. The compile-side twin is `PropertyCompileOutput` /
`_compile_properties` in `augur.sim.compiler`."""

from __future__ import annotations

import numpy as np
import polars as pl

from finance.augur.sim.codec.helpers import codes_to_strings, currency_quanta_column, frame_from_columns
from finance.augur.sim.compiler.plan import CompiledSimulation
from finance.augur.sim.events import EVENT_FRAMES
from finance.augur.sim.output import DenseSimulationOutput


def decode_property_purchases(
    plan: CompiledSimulation, output: DenseSimulationOutput
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Returns (property_purchases_frame, derived_transfers_frame).

    The transfers frame is the subset of purchases with a positive compiled stake contribution —
    the buyer-cash transfer that goes alongside the purchase event.
    """

    active = output.property_purchases  # (M, P, R)
    if active.any():
        months, props, rollouts = np.argwhere(active).T
    else:
        months = props = rollouts = np.array([], dtype=np.int64)
    cause_ids = codes_to_strings(plan, plan.properties.cause)[months, props]
    property_ids = codes_to_strings(plan, plan.properties.id)[props]
    location_ids = codes_to_strings(plan, plan.properties.location_id)[props]
    buyer_agents = codes_to_strings(plan, plan.properties.buyer_agent)[props]
    buyer_accounts = codes_to_strings(plan, plan.properties.buyer_account)[props]
    seller_agents = codes_to_strings(plan, plan.properties.seller_agent)[props]
    seller_accounts = codes_to_strings(plan, plan.properties.seller_account)[props]
    purchases = frame_from_columns(
        EVENT_FRAMES.property_purchases,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        property_id=property_ids,
        location_id=location_ids,
        buyer_agent_id=buyer_agents,
        purchase_price_quanta=currency_quanta_column(plan.properties.purchase_price[props]),
        closing_cost_quanta=currency_quanta_column(plan.properties.closing_cost[props]),
        adjusted_basis_quanta=currency_quanta_column(plan.properties.adjusted_basis[props]),
        stake_contribution_quanta=currency_quanta_column(plan.properties.stake_contribution[props]),
        equity_ledger_quanta=currency_quanta_column(plan.properties.equity_ledger[props]),
    )
    # A buyer-cash transfer is mechanically implied by the purchase event and its compiled stake.
    # Derive this at the decode boundary rather than storing/copying a duplicate event mask.
    transfer_mask = plan.properties.stake_contribution[props] > 0
    if transfer_mask.any():
        m_t = months[transfer_mask]
        p_t = props[transfer_mask]
        r_t = rollouts[transfer_mask]
        cause_t = np.array([f"{c}_buyer_cash" for c in cause_ids[transfer_mask]], dtype=object)
        transfers = frame_from_columns(
            EVENT_FRAMES.transfers,
            rollout_index=r_t,
            month_index=m_t,
            cause_id=cause_t,
            from_agent_id=buyer_agents[transfer_mask],
            from_account_id=buyer_accounts[transfer_mask],
            to_agent_id=seller_agents[transfer_mask],
            to_account_id=seller_accounts[transfer_mask],
            amount_quanta=currency_quanta_column(plan.properties.stake_contribution[p_t]),
            income_category=np.full(p_t.size, None, dtype=object),
        )
    else:
        transfers = EVENT_FRAMES.transfers.empty()
    return purchases, transfers
