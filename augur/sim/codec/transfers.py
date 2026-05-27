"""Transfer domain decoder. The compile-side twin is `TransferCompileOutput` +
`_compile_transfers` in `augur.sim.compiler`."""

from __future__ import annotations

import numpy as np
import polars as pl

from augur.sim.buffers import SimulationBuffers
from augur.sim.codec.helpers import codes_to_strings, frame_from_columns
from augur.sim.compiler import CompiledSimulation
from augur.sim.events import EVENT_FRAMES


def decode_transfers(plan: CompiledSimulation, buffers: SimulationBuffers) -> pl.DataFrame:
    active = buffers.transfers.active  # (M, S, R)
    months, slots, rollouts = np.argwhere(active).T if active.any() else (np.array([], dtype=np.int64),) * 3
    cause_ids = codes_to_strings(plan, plan.transfers.cause)[months, slots]
    from_agents = codes_to_strings(plan, plan.transfers.from_agent)[months, slots]
    from_accounts = codes_to_strings(plan, plan.transfers.from_account)[months, slots]
    to_agents = codes_to_strings(plan, plan.transfers.to_agent)[months, slots]
    to_accounts = codes_to_strings(plan, plan.transfers.to_account)[months, slots]
    amounts = buffers.transfers.amount[months, slots, rollouts]
    income_categories = np.where(plan.transfers.income_profile[months, slots] >= 0, "ordinary", None).astype(object)
    return frame_from_columns(
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
