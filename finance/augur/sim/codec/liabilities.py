"""Liability domain decoders: principal/payment state, mortgage origination + payment
events. The compile-side twin is `LiabilityCompileOutput` + `_compile_liabilities` in
`augur.sim.compiler`."""

from __future__ import annotations

import numpy as np
import polars as pl

from finance.augur.sim.codec.helpers import codes_to_strings, currency_quanta_column, frame_from_columns
from finance.augur.sim.compiler.plan import CompiledSimulation
from finance.augur.sim.events import EVENT_FRAMES
from finance.augur.sim.output import DenseSimulationOutput


def decode_mortgage_originations(plan: CompiledSimulation, output: DenseSimulationOutput) -> pl.DataFrame:
    active = output.mortgages.origination_active  # (M, liab, R)
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
        principal_quanta=currency_quanta_column(plan.liabilities.principal[liabs]),
        annual_interest_rate=plan.liabilities.annual_rate.astype(np.float64)[liabs],
        term_months=plan.liabilities.term_months.astype(np.int64)[liabs],
        monthly_payment_quanta=currency_quanta_column(plan.liabilities.monthly_payment[liabs]),
    )


def decode_mortgage_payments(plan: CompiledSimulation, output: DenseSimulationOutput) -> pl.DataFrame:
    active = output.mortgages.payment_active  # (M, liab, R)
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
        interest_quanta=currency_quanta_column(output.mortgages.payment_interest[months, liabs, rollouts]),
        principal_quanta=currency_quanta_column(output.mortgages.payment_principal[months, liabs, rollouts]),
        total_payment_quanta=currency_quanta_column(output.mortgages.payment_total[months, liabs, rollouts]),
    )
