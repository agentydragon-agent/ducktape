"""Tax domain decoders: ordinary income, capital gains, tax liabilities, and
year-end accrual/settlement events. The compile-side twin is `TaxCompileOutput` +
`TaxLiabilityCompileOutput` + `_compile_tax`/`_compile_tax_liabilities` in
`augur.sim.compiler`."""

from __future__ import annotations

import numpy as np
import polars as pl

from finance.augur.sim.codec.helpers import codes_to_strings, currency_quanta_column, frame_from_columns
from finance.augur.sim.compiler.plan import CompiledSimulation
from finance.augur.sim.enums import TaxBreakdownChannel
from finance.augur.sim.events import EVENT_FRAMES
from finance.augur.sim.output import DenseSimulationOutput


def decode_tax_accruals(plan: CompiledSimulation, output: DenseSimulationOutput) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Returns (tax_accruals_frame, tax_breakdowns_frame). Same active mask, two output frames."""

    breakdown = output.taxes.breakdown
    active = breakdown[TaxBreakdownChannel.ACCRUAL_ACTIVE] > 0  # (M, link, R)
    if active.any():
        months, links, rollouts = np.argwhere(active).T
    else:
        months = links = rollouts = np.array([], dtype=np.int64)
    profiles = plan.tax.link_profile.astype(np.int64)[links]
    agent_ids = codes_to_strings(plan, plan.tax.profile_agent)[profiles]
    jurisdiction_ids = codes_to_strings(plan, plan.tax.link_jurisdiction)[links]
    # cause_id is f"{agent_id}_{jurisdiction_id}_year_end_accrual_m{month}".
    cause_ids = np.array(
        [f"{a}_{j}_year_end_accrual_m{m}" for a, j, m in zip(agent_ids, jurisdiction_ids, months, strict=True)],
        dtype=object,
    )
    breakdown = breakdown[:, months, links, rollouts]
    totals = breakdown[TaxBreakdownChannel.ORDINARY_TAX] + breakdown[TaxBreakdownChannel.CAPITAL_GAIN_TAX]
    accruals = frame_from_columns(
        EVENT_FRAMES.tax_accruals,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=agent_ids,
        jurisdiction_id=jurisdiction_ids,
        tax_year_end_month=months,
        amount_quanta=currency_quanta_column(totals),
    )
    breakdowns = frame_from_columns(
        EVENT_FRAMES.tax_breakdowns,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=agent_ids,
        jurisdiction_id=jurisdiction_ids,
        tax_year_end_month=months,
        ordinary_income_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.ORDINARY_INCOME]),
        ltcg_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.LTCG]),
        stcg_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.STCG]),
        standard_deduction_quanta=currency_quanta_column(plan.tax.link_standard_deduction[links]),
        mortgage_interest_deduction_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.MORTGAGE_DEDUCTION]),
        salt_deduction_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.SALT_DEDUCTION]),
        itemized_deduction_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.ITEMIZED_DEDUCTION]),
        ordinary_taxable_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.ORDINARY_TAXABLE]),
        capital_gain_taxable_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.CAPITAL_GAIN_TAXABLE]),
        ordinary_tax_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.ORDINARY_TAX]),
        capital_gain_tax_quanta=currency_quanta_column(breakdown[TaxBreakdownChannel.CAPITAL_GAIN_TAX]),
        total_tax_quanta=currency_quanta_column(totals),
    )
    return accruals, breakdowns


def decode_tax_settlements(plan: CompiledSimulation, output: DenseSimulationOutput) -> pl.DataFrame:
    active = output.taxes.settlement_active  # (M, profile, R)
    if active.any():
        months, profiles, rollouts = np.argwhere(active).T
    else:
        months = profiles = rollouts = np.array([], dtype=np.int64)
    agent_ids = codes_to_strings(plan, plan.tax.profile_agent)[profiles]
    year_end = output.taxes.settlement_year_end[months, profiles, rollouts].astype(np.int64)
    tax_years = (year_end - 11) // 12
    cause_ids = np.array([f"{a}_tax_settlement_y{y}" for a, y in zip(agent_ids, tax_years, strict=True)], dtype=object)
    return frame_from_columns(
        EVENT_FRAMES.tax_settlements,
        rollout_index=rollouts,
        month_index=months,
        cause_id=cause_ids,
        agent_id=agent_ids,
        tax_year_end_month=year_end,
        amount_quanta=currency_quanta_column(output.taxes.settlement_amount[months, profiles, rollouts]),
    )
