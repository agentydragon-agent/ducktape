"""Cashflow decoder. The compile-side twin is `CashflowCompileOutput` + `compile_cashflows`."""

from __future__ import annotations

import numpy as np
import polars as pl

from finance.augur.sim.codec.helpers import code_column, currency_quanta_column, frame_from_columns
from finance.augur.sim.compiler.plan import CompiledSimulation
from finance.augur.sim.events import EVENT_FRAMES
from finance.augur.sim.output import DenseSimulationOutput


def _income_category_column(mask: np.ndarray) -> pl.Series:
    values: list[str | None] = [None] * int(mask.size)
    for index in np.flatnonzero(mask):
        values[int(index)] = "ordinary"
    return pl.Series("income_category", values, dtype=pl.Utf8)


def decode_cashflows(plan: CompiledSimulation, output: DenseSimulationOutput) -> pl.DataFrame:
    active = output.cashflows.active  # (M, S, R)
    months, slots, rollouts = np.argwhere(active).T if active.any() else (np.array([], dtype=np.int64),) * 3
    cashflows = plan.cashflows
    execution = cashflows.execution
    return frame_from_columns(
        EVENT_FRAMES.transfers,
        rollout_index=rollouts,
        month_index=months,
        cause_id=code_column(plan, cashflows.cause[months, slots]),
        from_agent_id=code_column(plan, cashflows.from_agent[months, slots]),
        from_account_id=code_column(plan, cashflows.from_account[months, slots]),
        to_agent_id=code_column(plan, cashflows.to_agent[months, slots]),
        to_account_id=code_column(plan, cashflows.to_account[months, slots]),
        amount_quanta=currency_quanta_column(output.cashflows.amount[months, slots, rollouts]),
        income_category=_income_category_column(execution.income_profile[months, slots] >= 0),
    )
