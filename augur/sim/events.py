"""Event log for the simulation.

Every state-changing happening is a row on an event-kind frame.
`EventLog` bundles all the kind frames together so the simulate loop
can hand one object to `apply_events`. Each kind frame's schema is
keyed by `(rollout_index, month_index, cause_id)` plus the kind-
specific columns.

At spike 1 step 4: `transfers`, `asset_purchases`, and
`lot_dispositions` are populated. Later layers add tax accruals +
payments, tax settlements, mortgage payments, obligation accruals +
settlements, occupancy-mode changes, depreciation accruals, failure
events, etc.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import polars as pl

TRANSFER_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "from_agent_id": pl.Utf8(),
    "from_account_id": pl.Utf8(),
    "to_agent_id": pl.Utf8(),
    "to_account_id": pl.Utf8(),
    "amount_usd": pl.Float64(),
    # Tax classification: when set (e.g. "ordinary" for W-2 wages),
    # apply_events increments the recipient's ordinary_income_ytd.
    # Null for non-income transfers (e.g. expense payments).
    "income_category": pl.Utf8(),
}


def concat_event_frames(frames: Iterable[pl.DataFrame], schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Concatenate event frames while preserving the typed empty case.

    Empty event streams are common. Prefixing a schema-only frame
    makes the empty and non-empty cases use the same code path.
    """
    return pl.concat([pl.DataFrame(schema=schema), *frames]).select(list(schema.keys()))


# `AssetPurchase` records the creation of a new tax lot — either an
# initial holding seeded at scenario start, or (later) an in-sim buy.
# Initial-holding purchases at spike-1 step 4 do not draw cash; an
# in-sim buy in a later layer will be paired with a transfer that
# debits cash. The lot the purchase creates is keyed by
# `(rollout_index, lot_id)` and shows up as a new row in
# `state.asset_lots` with `remaining_quantity = quantity`.
ASSET_PURCHASE_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "asset_id": pl.Utf8(),
    "lot_id": pl.Utf8(),
    "quantity": pl.Float64(),
    "cost_basis_per_unit_usd": pl.Float64(),
}

# `TaxAccrual` records a year-end tax computation: a single
# year's ordinary income for one agent under one jurisdiction has
# been bracket-walked, and the resulting tax `amount_usd` is now
# owed. apply_events appends a row to `state.tax_liabilities` and
# zeroes the agent's `ordinary_income_ytd` for the next year.
TAX_ACCRUAL_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "jurisdiction_id": pl.Utf8(),
    "tax_year_end_month": pl.Int64(),
    "amount_usd": pl.Float64(),
}

# `TaxBreakdown` records the inputs and component tax amounts behind
# each year-end accrual. It is audit/output only; `apply_events` does
# not mutate state from this frame.
TAX_BREAKDOWN_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "jurisdiction_id": pl.Utf8(),
    "tax_year_end_month": pl.Int64(),
    "ordinary_income_usd": pl.Float64(),
    "ltcg_usd": pl.Float64(),
    "stcg_usd": pl.Float64(),
    "standard_deduction_usd": pl.Float64(),
    "ordinary_taxable_usd": pl.Float64(),
    "capital_gain_taxable_usd": pl.Float64(),
    "ordinary_tax_usd": pl.Float64(),
    "capital_gain_tax_usd": pl.Float64(),
    "total_tax_usd": pl.Float64(),
}

# `TaxSettlement` applies paid tax dollars against already-accrued
# liabilities for an agent and tax year. Cash still moves through
# Transfer events; this frame is the liability-side settlement.
TAX_SETTLEMENT_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "tax_year_end_month": pl.Int64(),
    "amount_usd": pl.Float64(),
}

OBLIGATION_ACCRUAL_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "obligation_id": pl.Utf8(),
    "obligation_type": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "from_account_id": pl.Utf8(),
    "to_agent_id": pl.Utf8(),
    "to_account_id": pl.Utf8(),
    "amount_due_usd": pl.Float64(),
}

OBLIGATION_SETTLEMENT_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "obligation_id": pl.Utf8(),
    "obligation_type": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "from_account_id": pl.Utf8(),
    "amount_due_usd": pl.Float64(),
    "amount_paid_usd": pl.Float64(),
    "shortfall_usd": pl.Float64(),
    "attempted_funding_sources": pl.Utf8(),
}

PROPERTY_PURCHASE_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "property_id": pl.Utf8(),
    "location_id": pl.Utf8(),
    "buyer_agent_id": pl.Utf8(),
    "purchase_price_usd": pl.Float64(),
    "closing_cost_usd": pl.Float64(),
    "adjusted_basis_usd": pl.Float64(),
    "ownership_pct": pl.Float64(),
    "stake_contribution_usd": pl.Float64(),
    "equity_ledger_usd": pl.Float64(),
}

MORTGAGE_ORIGINATION_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "liability_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "payment_account_id": pl.Utf8(),
    "counterparty_agent_id": pl.Utf8(),
    "counterparty_account_id": pl.Utf8(),
    "property_id": pl.Utf8(),
    "principal_usd": pl.Float64(),
    "annual_interest_rate": pl.Float64(),
    "term_months": pl.Int64(),
    "monthly_payment_usd": pl.Float64(),
}

MORTGAGE_PAYMENT_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "liability_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "counterparty_agent_id": pl.Utf8(),
    "property_id": pl.Utf8(),
    "from_account_id": pl.Utf8(),
    "to_account_id": pl.Utf8(),
    "interest_usd": pl.Float64(),
    "principal_usd": pl.Float64(),
    "total_payment_usd": pl.Float64(),
}

# `RolloutFailure` flags a rollout as having run out of disposable
# wealth — agent's cash is negative even after the floor-triggered
# sale policy has done its best. Once flagged, the rollout stays
# failed for the rest of the sim (L11.2).
ROLLOUT_FAILURE_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "deficit_usd": pl.Float64(),
    "obligation_id": pl.Utf8(),
    "obligation_type": pl.Utf8(),
    "amount_due_usd": pl.Float64(),
    "amount_paid_usd": pl.Float64(),
    "shortfall_usd": pl.Float64(),
    "attempted_funding_sources": pl.Utf8(),
}

# `LotDisposition` records the consumption of part (or all) of one
# lot by one logical sale. A single AssetSale "sell N units of vti"
# decomposes into one disposition row per lot the sale ate into;
# `cause_id` groups all dispositions of the same sale for downstream
# tax classification. Holding period for LTCG/STCG is
# `month_index - purchase_month_index`.
LOT_DISPOSITION_EVENT_SCHEMA: dict[str, pl.DataType] = {
    "rollout_index": pl.Int64(),
    "month_index": pl.Int64(),
    "cause_id": pl.Utf8(),
    "agent_id": pl.Utf8(),
    "asset_id": pl.Utf8(),
    "lot_id": pl.Utf8(),
    "purchase_month_index": pl.Int64(),
    "units_sold": pl.Float64(),
    "cost_basis_consumed_usd": pl.Float64(),
    "proceeds_usd": pl.Float64(),
    "proceeds_account_id": pl.Utf8(),
}


@dataclass(frozen=True)
class EventLog:
    """Per-step or per-simulation collection of events, one frame
    per event kind."""

    transfers: pl.DataFrame
    asset_purchases: pl.DataFrame
    lot_dispositions: pl.DataFrame
    tax_accruals: pl.DataFrame
    tax_breakdowns: pl.DataFrame
    tax_settlements: pl.DataFrame
    obligation_accruals: pl.DataFrame
    obligation_settlements: pl.DataFrame
    property_purchases: pl.DataFrame
    mortgage_originations: pl.DataFrame
    mortgage_payments: pl.DataFrame
    rollout_failures: pl.DataFrame

    @classmethod
    def empty(cls) -> EventLog:
        return cls(
            transfers=pl.DataFrame(schema=TRANSFER_EVENT_SCHEMA),
            asset_purchases=pl.DataFrame(schema=ASSET_PURCHASE_EVENT_SCHEMA),
            lot_dispositions=pl.DataFrame(schema=LOT_DISPOSITION_EVENT_SCHEMA),
            tax_accruals=pl.DataFrame(schema=TAX_ACCRUAL_EVENT_SCHEMA),
            tax_breakdowns=pl.DataFrame(schema=TAX_BREAKDOWN_EVENT_SCHEMA),
            tax_settlements=pl.DataFrame(schema=TAX_SETTLEMENT_EVENT_SCHEMA),
            obligation_accruals=pl.DataFrame(schema=OBLIGATION_ACCRUAL_EVENT_SCHEMA),
            obligation_settlements=pl.DataFrame(schema=OBLIGATION_SETTLEMENT_EVENT_SCHEMA),
            property_purchases=pl.DataFrame(schema=PROPERTY_PURCHASE_EVENT_SCHEMA),
            mortgage_originations=pl.DataFrame(schema=MORTGAGE_ORIGINATION_EVENT_SCHEMA),
            mortgage_payments=pl.DataFrame(schema=MORTGAGE_PAYMENT_EVENT_SCHEMA),
            rollout_failures=pl.DataFrame(schema=ROLLOUT_FAILURE_EVENT_SCHEMA),
        )
