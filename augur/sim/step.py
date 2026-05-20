"""`step_emit_events` — pure function that reads state + scenario +
month index and returns the events for that month.

At the current spike the step emits:

  - transfer events for scheduled + recurring transfers active at
    this month, optionally tagged with an `income_category`;
  - lot_disposition events for scheduled asset sales (FIFO across
    the agent's lots);
  - tax_accrual events at the end of each tax year (month_index
    in {11, 23, 35, ...}) — one per (taxed agent, jurisdiction),
    computed by bracket-walking end-of-year ordinary income minus
    the jurisdiction's standard deduction;
  - due-now obligations for configured required payments, mortgage
    payments, property tax, estimated-tax markers, and January
    true-ups after prior year-end accruals are known.

The step does not mutate `state`. The simulate loop calls
`apply_events(state, step_result)` separately. apply_events
processes income transfers before tax accruals so the accrual
amount the step computes is consistent with the YTD that apply
will produce.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from augur.sim.events import EVENT_FRAMES, EventLog
from augur.sim.jurisdictions import Jurisdiction
from augur.sim.locations import Location
from augur.sim.market import MarketContext
from augur.sim.scenario import (
    FloorTriggeredSalePolicy,
    PropertyTaxPolicy,
    RecurringObligation,
    RecurringTransfer,
    Scenario,
    ScheduledAssetSale,
    ScheduledObligation,
    ScheduledPropertyPurchase,
    ScheduledTransfer,
    TaxProfile,
)
from augur.sim.state import StateCrossSection
from augur.sim.tax import apply_brackets, apply_ltcg_brackets


@dataclass(frozen=True)
class _TaxYearEvents:
    accruals: pl.DataFrame
    breakdowns: pl.DataFrame


@dataclass(frozen=True)
class _TaxPaymentObligationEvents:
    obligation_accruals: pl.DataFrame
    settlements: pl.DataFrame


@dataclass(frozen=True)
class _DueNowSettlementEvents:
    obligation_accruals: pl.DataFrame
    obligation_settlements: pl.DataFrame
    transfers: pl.DataFrame
    lot_dispositions: pl.DataFrame
    mortgage_payments: pl.DataFrame
    tax_settlements: pl.DataFrame
    rollout_failures: pl.DataFrame


def step_emit_scheduled_events(
    *,
    state: StateCrossSection,
    scenario: Scenario,
    market: MarketContext,
    jurisdictions: dict[str, Jurisdiction],
    locations: dict[str, Location],
    month: int,
    rollout_count: int,
) -> EventLog:
    """Phase 1 of the month step: scheduled / recurring transfers,
    scheduled asset sales, property purchases, mortgage originations,
    and year-end tax accruals. Pure: does not mutate `state`."""
    transfers = _emit_transfers(scenario, month, rollout_count)
    property_purchases = _emit_property_purchases(scenario, month, rollout_count)
    mortgage_originations = _emit_mortgage_originations(scenario, month, rollout_count)
    property_cash_transfers = _property_purchase_transfer_events(scenario, property_purchases)
    dispositions = _emit_lot_dispositions(state, scenario, market, month)
    tax_year_events = _emit_year_end_tax_events(
        state=state,
        scenario=scenario,
        jurisdictions=jurisdictions,
        month=month,
        transfers=transfers,
        dispositions=dispositions,
    )
    return EventLog.from_frames(
        {
            "transfers": EVENT_FRAMES.transfers.concat([transfers, property_cash_transfers]),
            "lot_dispositions": dispositions,
            "tax_accruals": tax_year_events.accruals,
            "tax_breakdowns": tax_year_events.breakdowns,
            "property_purchases": property_purchases,
            "mortgage_originations": mortgage_originations,
        }
    )


def step_emit_policy_events(
    *, state: StateCrossSection, scenario: Scenario, market: MarketContext, locations: dict[str, Location], month: int
) -> EventLog:
    """Phase 2 of the month step: discretionary policies, due-now
    obligation settlement, and failure detection. Runs on the
    post-phase-1 state so the floor check sees cash after all
    scheduled events have applied."""
    floor_dispositions = _emit_floor_triggered_sales(state, scenario, market, month)
    due_now = _emit_due_now_obligations_and_settlements(
        state=state,
        scenario=scenario,
        market=market,
        locations=locations,
        base_dispositions=floor_dispositions,
        month=month,
    )
    dispositions = EVENT_FRAMES.lot_dispositions.concat([floor_dispositions, due_now.lot_dispositions])
    cash_failures = _emit_rollout_failures(
        state=state, scenario=scenario, policy_dispositions=dispositions, transfers=due_now.transfers, month=month
    )
    return EventLog.from_frames(
        {
            "transfers": due_now.transfers,
            "lot_dispositions": dispositions,
            "tax_settlements": due_now.tax_settlements,
            "obligation_accruals": due_now.obligation_accruals,
            "obligation_settlements": due_now.obligation_settlements,
            "mortgage_payments": due_now.mortgage_payments,
            "rollout_failures": EVENT_FRAMES.rollout_failures.concat([due_now.rollout_failures, cash_failures]),
        }
    )


def _emit_transfers(scenario: Scenario, month: int, rollout_count: int) -> pl.DataFrame:
    """Emit Transfer event rows for every scheduled or recurring
    transfer active at this month. Scheduled transfers fire only at
    their configured month; recurring transfers fire every month in
    `[start_month, end_month]` (or through horizon end). One row per
    (transfer, rollout)."""
    active: list[ScheduledTransfer | RecurringTransfer] = [t for t in scenario.scheduled_transfers if t.month == month]
    active.extend(t for t in scenario.recurring_transfers if t.is_active_at(month))
    blocks: list[pl.DataFrame] = []
    if active:
        rollouts = pl.DataFrame({"rollout_index": list(range(rollout_count))}, schema={"rollout_index": pl.Int64()})
        blocks = [_transfer_block_per_rollout(t, rollouts, month) for t in active]
    return EVENT_FRAMES.transfers.concat(blocks)


def _transfer_block_per_rollout(
    t: ScheduledTransfer | RecurringTransfer, rollouts: pl.DataFrame, month: int
) -> pl.DataFrame:
    """One row per rollout for one transfer config. The rollout
    dimension is expanded vectorized — no Python loop over rollouts.
    Handles both ScheduledTransfer (one-off at a specific month) and
    RecurringTransfer (firing at this active month) — same event
    schema, only the cadence config differs."""
    return rollouts.with_columns(
        pl.lit(month, dtype=pl.Int64()).alias("month_index"),
        pl.lit(t.cause_id, dtype=pl.Utf8()).alias("cause_id"),
        pl.lit(t.from_agent_id, dtype=pl.Utf8()).alias("from_agent_id"),
        pl.lit(t.from_account_id, dtype=pl.Utf8()).alias("from_account_id"),
        pl.lit(t.to_agent_id, dtype=pl.Utf8()).alias("to_agent_id"),
        pl.lit(t.to_account_id, dtype=pl.Utf8()).alias("to_account_id"),
        pl.lit(t.amount_usd, dtype=pl.Float64()).alias("amount_usd"),
        pl.lit(t.income_category, dtype=pl.Utf8()).alias("income_category"),
    )


def _emit_property_purchases(scenario: Scenario, month: int, rollout_count: int) -> pl.DataFrame:
    purchases = [purchase for purchase in scenario.scheduled_property_purchases if purchase.month == month]
    if not purchases:
        return EVENT_FRAMES.property_purchases.empty()
    rollouts = pl.DataFrame({"rollout_index": list(range(rollout_count))}, schema={"rollout_index": pl.Int64()})
    return EVENT_FRAMES.property_purchases.concat(
        [_property_purchase_block_per_rollout(purchase, rollouts, month) for purchase in purchases]
    )


def _property_purchase_block_per_rollout(
    purchase: ScheduledPropertyPurchase, rollouts: pl.DataFrame, month: int
) -> pl.DataFrame:
    mortgage_principal = purchase.mortgage.principal_usd if purchase.mortgage is not None else 0.0
    return rollouts.with_columns(
        pl.lit(month, dtype=pl.Int64()).alias("month_index"),
        pl.lit(purchase.cause_id, dtype=pl.Utf8()).alias("cause_id"),
        pl.lit(purchase.property_id, dtype=pl.Utf8()).alias("property_id"),
        pl.lit(purchase.location_id, dtype=pl.Utf8()).alias("location_id"),
        pl.lit(purchase.buyer_agent_id, dtype=pl.Utf8()).alias("buyer_agent_id"),
        pl.lit(purchase.purchase_price_usd, dtype=pl.Float64()).alias("purchase_price_usd"),
        pl.lit(purchase.buyer_closing_cost_usd, dtype=pl.Float64()).alias("closing_cost_usd"),
        pl.lit(purchase.purchase_price_usd + purchase.buyer_closing_cost_usd, dtype=pl.Float64()).alias(
            "adjusted_basis_usd"
        ),
        pl.lit(purchase.ownership_pct, dtype=pl.Float64()).alias("ownership_pct"),
        pl.lit(purchase.down_payment_usd + purchase.buyer_closing_cost_usd, dtype=pl.Float64()).alias(
            "stake_contribution_usd"
        ),
        pl.lit(purchase.purchase_price_usd - mortgage_principal, dtype=pl.Float64()).alias("equity_ledger_usd"),
    ).pipe(EVENT_FRAMES.property_purchases.normalize)


def _emit_mortgage_originations(scenario: Scenario, month: int, rollout_count: int) -> pl.DataFrame:
    purchases = [
        purchase
        for purchase in scenario.scheduled_property_purchases
        if purchase.month == month and purchase.mortgage is not None
    ]
    if not purchases:
        return EVENT_FRAMES.mortgage_originations.empty()
    rollouts = pl.DataFrame({"rollout_index": list(range(rollout_count))}, schema={"rollout_index": pl.Int64()})
    return EVENT_FRAMES.mortgage_originations.concat(
        [_mortgage_origination_block_per_rollout(purchase, rollouts, month) for purchase in purchases]
    )


def _mortgage_origination_block_per_rollout(
    purchase: ScheduledPropertyPurchase, rollouts: pl.DataFrame, month: int
) -> pl.DataFrame:
    mortgage = purchase.mortgage
    if mortgage is None:
        raise ValueError("_mortgage_origination_block_per_rollout requires mortgage terms")
    return rollouts.with_columns(
        pl.lit(month, dtype=pl.Int64()).alias("month_index"),
        pl.lit(f"{purchase.cause_id}_mortgage_origination", dtype=pl.Utf8()).alias("cause_id"),
        pl.lit(mortgage.liability_id, dtype=pl.Utf8()).alias("liability_id"),
        pl.lit(purchase.buyer_agent_id, dtype=pl.Utf8()).alias("agent_id"),
        pl.lit(purchase.buyer_account_id, dtype=pl.Utf8()).alias("payment_account_id"),
        pl.lit(mortgage.lender_agent_id, dtype=pl.Utf8()).alias("counterparty_agent_id"),
        pl.lit(mortgage.lender_account_id, dtype=pl.Utf8()).alias("counterparty_account_id"),
        pl.lit(purchase.property_id, dtype=pl.Utf8()).alias("property_id"),
        pl.lit(mortgage.principal_usd, dtype=pl.Float64()).alias("principal_usd"),
        pl.lit(mortgage.annual_interest_rate, dtype=pl.Float64()).alias("annual_interest_rate"),
        pl.lit(int(mortgage.term_months), dtype=pl.Int64()).alias("term_months"),
        pl.lit(
            _mortgage_monthly_payment_usd(mortgage.principal_usd, mortgage.annual_interest_rate, mortgage.term_months),
            dtype=pl.Float64(),
        ).alias("monthly_payment_usd"),
    ).pipe(EVENT_FRAMES.mortgage_originations.normalize)


def _mortgage_monthly_payment_usd(principal_usd: float, annual_interest_rate: float, term_months: int) -> float:
    monthly_rate = annual_interest_rate / 12.0
    if monthly_rate == 0:
        return principal_usd / term_months
    return principal_usd * monthly_rate / (1.0 - (1.0 + monthly_rate) ** -term_months)


def _property_purchase_transfer_events(scenario: Scenario, purchases: pl.DataFrame) -> pl.DataFrame:
    if purchases.is_empty():
        return EVENT_FRAMES.transfers.empty()
    blocks = []
    for purchase in scenario.scheduled_property_purchases:
        purchase_rows = purchases.filter(pl.col("cause_id") == purchase.cause_id)
        if purchase_rows.is_empty():
            continue
        amount = purchase.down_payment_usd + purchase.buyer_closing_cost_usd
        if amount <= 0:
            continue
        blocks.append(
            purchase_rows.with_columns(
                pl.lit(f"{purchase.cause_id}_buyer_cash", dtype=pl.Utf8()).alias("cause_id"),
                pl.lit(purchase.buyer_agent_id, dtype=pl.Utf8()).alias("from_agent_id"),
                pl.lit(purchase.buyer_account_id, dtype=pl.Utf8()).alias("from_account_id"),
                pl.lit(purchase.seller_agent_id, dtype=pl.Utf8()).alias("to_agent_id"),
                pl.lit(purchase.seller_account_id, dtype=pl.Utf8()).alias("to_account_id"),
                pl.lit(amount, dtype=pl.Float64()).alias("amount_usd"),
                pl.lit(None, dtype=pl.Utf8()).alias("income_category"),
            ).pipe(EVENT_FRAMES.transfers.normalize)
        )
    return EVENT_FRAMES.transfers.concat(blocks)


def _emit_mortgage_payments(state: StateCrossSection, month: int) -> pl.DataFrame:
    liabilities = state.liabilities.filter((pl.col("principal_usd") > 0) & (pl.col("origination_month_index") < month))
    if liabilities.is_empty():
        return EVENT_FRAMES.mortgage_payments.empty()
    monthly_interest = pl.col("principal_usd") * pl.col("annual_interest_rate") / 12.0
    total_payment = pl.min_horizontal(pl.col("monthly_payment_usd"), pl.col("principal_usd") + monthly_interest)
    return (
        liabilities.with_columns(
            _interest_usd=pl.min_horizontal(monthly_interest, total_payment), _total_payment_usd=total_payment
        )
        .with_columns(_principal_usd=pl.max_horizontal(0.0, pl.col("_total_payment_usd") - pl.col("_interest_usd")))
        .with_columns(
            pl.lit(month, dtype=pl.Int64()).alias("month_index"),
            pl.concat_str([pl.col("liability_id"), pl.lit("_payment_m"), pl.lit(str(month))]).alias("cause_id"),
            pl.col("payment_account_id").alias("from_account_id"),
            pl.col("counterparty_account_id").alias("to_account_id"),
            pl.col("_interest_usd").alias("interest_usd"),
            pl.col("_principal_usd").alias("principal_usd"),
            pl.col("_total_payment_usd").alias("total_payment_usd"),
        )
        .pipe(EVENT_FRAMES.mortgage_payments.normalize)
    )


def _mortgage_payment_obligations(mortgage_payments: pl.DataFrame) -> pl.DataFrame:
    if mortgage_payments.is_empty():
        return EVENT_FRAMES.obligation_accruals.empty()
    return mortgage_payments.with_columns(
        pl.col("cause_id").alias("obligation_id"),
        pl.lit("mortgage_payment", dtype=pl.Utf8()).alias("obligation_type"),
        pl.col("counterparty_agent_id").alias("to_agent_id"),
        pl.col("total_payment_usd").alias("amount_due_usd"),
    ).pipe(EVENT_FRAMES.obligation_accruals.normalize)


def _emit_property_tax_obligations(
    *, state: StateCrossSection, scenario: Scenario, locations: dict[str, Location], month: int
) -> pl.DataFrame:
    active = [policy for policy in scenario.property_tax_policies if policy.is_active_at(month)]
    if not active or state.property_state.is_empty():
        return EVENT_FRAMES.obligation_accruals.empty()
    return EVENT_FRAMES.obligation_accruals.concat(
        [_property_tax_obligation_block(state, policy, locations, month) for policy in active]
    )


def _property_tax_obligation_block(
    state: StateCrossSection, policy: PropertyTaxPolicy, locations: dict[str, Location], month: int
) -> pl.DataFrame:
    property_rows = state.property_state.filter(
        (pl.col("property_id") == policy.property_id) & (pl.col("purchase_month_index") < month)
    )
    if property_rows.is_empty():
        return EVENT_FRAMES.obligation_accruals.empty()
    rate_rows = pl.DataFrame(
        {
            "location_id": list(locations),
            "_annual_tax_rate": [location.annual_property_tax_rate for location in locations.values()],
        },
        schema={"location_id": pl.Utf8(), "_annual_tax_rate": pl.Float64()},
    )
    taxed = (
        property_rows.join(rate_rows, on="location_id", how="left")
        .with_columns(
            _annual_tax_rate=pl.lit(policy.annual_tax_rate, dtype=pl.Float64())
            if policy.annual_tax_rate is not None
            else pl.col("_annual_tax_rate")
        )
        .with_columns(amount_usd=pl.col("adjusted_basis_usd") * pl.col("_annual_tax_rate") / 12.0)
        .filter(pl.col("amount_usd") > 0)
    )
    return taxed.with_columns(
        pl.lit(month, dtype=pl.Int64()).alias("month_index"),
        pl.lit(f"{policy.property_id}_property_tax_m{month}", dtype=pl.Utf8()).alias("cause_id"),
        pl.lit(f"{policy.property_id}_property_tax_m{month}", dtype=pl.Utf8()).alias("obligation_id"),
        pl.lit("property_tax", dtype=pl.Utf8()).alias("obligation_type"),
        pl.lit(policy.owner_agent_id, dtype=pl.Utf8()).alias("agent_id"),
        pl.lit(policy.from_account_id, dtype=pl.Utf8()).alias("from_account_id"),
        pl.lit(policy.tax_authority_agent_id, dtype=pl.Utf8()).alias("to_agent_id"),
        pl.lit(policy.tax_authority_account_id, dtype=pl.Utf8()).alias("to_account_id"),
        pl.col("amount_usd").alias("amount_due_usd"),
    ).pipe(EVENT_FRAMES.obligation_accruals.normalize)


def _emit_configured_obligations(scenario: Scenario, month: int, rollouts: pl.DataFrame) -> pl.DataFrame:
    active: list[ScheduledObligation | RecurringObligation] = [
        obligation for obligation in scenario.scheduled_obligations if obligation.month == month
    ]
    active.extend(obligation for obligation in scenario.recurring_obligations if obligation.is_active_at(month))
    if not active:
        return EVENT_FRAMES.obligation_accruals.empty()
    return EVENT_FRAMES.obligation_accruals.concat(
        [_configured_obligation_block_per_rollout(obligation, rollouts, month) for obligation in active]
    )


def _configured_obligation_block_per_rollout(
    obligation: ScheduledObligation | RecurringObligation, rollouts: pl.DataFrame, month: int
) -> pl.DataFrame:
    return rollouts.with_columns(
        pl.lit(month, dtype=pl.Int64()).alias("month_index"),
        pl.lit(f"{obligation.obligation_id}_m{month}", dtype=pl.Utf8()).alias("cause_id"),
        pl.lit(f"{obligation.obligation_id}_m{month}", dtype=pl.Utf8()).alias("obligation_id"),
        pl.lit(obligation.obligation_type, dtype=pl.Utf8()).alias("obligation_type"),
        pl.lit(obligation.agent_id, dtype=pl.Utf8()).alias("agent_id"),
        pl.lit(obligation.from_account_id, dtype=pl.Utf8()).alias("from_account_id"),
        pl.lit(obligation.to_agent_id, dtype=pl.Utf8()).alias("to_agent_id"),
        pl.lit(obligation.to_account_id, dtype=pl.Utf8()).alias("to_account_id"),
        pl.lit(obligation.amount_due_usd, dtype=pl.Float64()).alias("amount_due_usd"),
    ).pipe(EVENT_FRAMES.obligation_accruals.normalize)


def _emit_due_now_obligations_and_settlements(
    *,
    state: StateCrossSection,
    scenario: Scenario,
    market: MarketContext,
    locations: dict[str, Location],
    base_dispositions: pl.DataFrame,
    month: int,
) -> _DueNowSettlementEvents:
    active_rollouts = state.rollout_status.filter(pl.col("status") == "active").select("rollout_index")
    mortgage_payments = _emit_mortgage_payments(state, month)
    tax_payment_events = _emit_tax_payment_obligations(state=state, profiles=scenario.tax_profiles, month=month)
    obligations = EVENT_FRAMES.obligation_accruals.concat(
        [
            _emit_configured_obligations(scenario, month, active_rollouts),
            _mortgage_payment_obligations(mortgage_payments),
            _emit_property_tax_obligations(state=state, scenario=scenario, locations=locations, month=month),
            tax_payment_events.obligation_accruals,
        ]
    )
    settlement = _settle_due_now_obligations(
        state=state,
        scenario=scenario,
        market=market,
        obligations=obligations,
        base_dispositions=base_dispositions,
        month=month,
    )
    return _DueNowSettlementEvents(
        obligation_accruals=settlement.obligation_accruals,
        obligation_settlements=settlement.obligation_settlements,
        transfers=settlement.transfers,
        lot_dispositions=settlement.lot_dispositions,
        mortgage_payments=_paid_mortgage_payment_events(mortgage_payments, settlement.obligation_settlements),
        tax_settlements=_paid_tax_settlement_events(tax_payment_events.settlements, settlement.obligation_settlements),
        rollout_failures=settlement.rollout_failures,
    )


def _settle_due_now_obligations(
    *,
    state: StateCrossSection,
    scenario: Scenario,
    market: MarketContext,
    obligations: pl.DataFrame,
    base_dispositions: pl.DataFrame,
    month: int,
) -> _DueNowSettlementEvents:
    active_rollouts = state.rollout_status.filter(pl.col("status") == "active").select("rollout_index")
    active_obligations = obligations.filter(pl.col("amount_due_usd") > 0).join(active_rollouts, on="rollout_index")
    if active_obligations.is_empty():
        return _empty_due_now_settlement_events(active_obligations)
    due_by_account = _policy_funding_sources_for_obligations(
        scenario, _obligation_due_by_account(state, active_obligations, base_dispositions)
    )
    funding_dispositions = _funding_dispositions_for_due_groups(
        state=state,
        scenario=scenario,
        market=market,
        due_by_account=due_by_account,
        base_dispositions=base_dispositions,
        month=month,
    )
    funding_proceeds = _disposition_proceeds_by_account(funding_dispositions).rename(
        {"_proceeds_usd": "_funding_proceeds_usd"}
    )
    funded = (
        due_by_account.join(funding_proceeds, on=["rollout_index", "agent_id", "from_account_id"], how="left")
        .with_columns(
            _available_after_funding_usd=pl.col("_available_before_funding_usd")
            + pl.col("_funding_proceeds_usd").fill_null(0.0),
            _account_shortfall_usd=pl.max_horizontal(
                0.0,
                pl.col("_total_due_usd")
                - (pl.col("_available_before_funding_usd") + pl.col("_funding_proceeds_usd").fill_null(0.0)),
            ),
            _fully_paid=(
                pl.col("_available_before_funding_usd") + pl.col("_funding_proceeds_usd").fill_null(0.0)
                >= pl.col("_total_due_usd") - 1e-9
            ),
        )
        .select(
            "rollout_index",
            "agent_id",
            "from_account_id",
            "_total_due_usd",
            "_account_shortfall_usd",
            "_fully_paid",
            "_attempted_funding_sources",
        )
    )
    joined = active_obligations.join(funded, on=["rollout_index", "agent_id", "from_account_id"], how="left")
    settled = joined.with_columns(
        amount_paid_usd=pl.when(pl.col("_fully_paid")).then(pl.col("amount_due_usd")).otherwise(0.0),
        shortfall_usd=pl.when(pl.col("_fully_paid"))
        .then(0.0)
        .otherwise(pl.col("amount_due_usd") / pl.col("_total_due_usd") * pl.col("_account_shortfall_usd")),
        attempted_funding_sources=pl.col("_attempted_funding_sources").fill_null(""),
    )
    return _DueNowSettlementEvents(
        obligation_accruals=active_obligations,
        obligation_settlements=settled.pipe(EVENT_FRAMES.obligation_settlements.normalize),
        transfers=_obligation_payment_transfers(settled),
        lot_dispositions=funding_dispositions,
        mortgage_payments=EVENT_FRAMES.mortgage_payments.empty(),
        tax_settlements=EVENT_FRAMES.tax_settlements.empty(),
        rollout_failures=_obligation_failure_events(settled, month),
    )


def _empty_due_now_settlement_events(obligations: pl.DataFrame) -> _DueNowSettlementEvents:
    return _DueNowSettlementEvents(
        obligation_accruals=obligations,
        obligation_settlements=EVENT_FRAMES.obligation_settlements.empty(),
        transfers=EVENT_FRAMES.transfers.empty(),
        lot_dispositions=EVENT_FRAMES.lot_dispositions.empty(),
        mortgage_payments=EVENT_FRAMES.mortgage_payments.empty(),
        tax_settlements=EVENT_FRAMES.tax_settlements.empty(),
        rollout_failures=EVENT_FRAMES.rollout_failures.empty(),
    )


def _obligation_due_by_account(
    state: StateCrossSection, obligations: pl.DataFrame, base_dispositions: pl.DataFrame
) -> pl.DataFrame:
    due = obligations.group_by(["rollout_index", "agent_id", "from_account_id"]).agg(
        pl.col("amount_due_usd").sum().alias("_total_due_usd")
    )
    cash = state.cash_balances.rename({"account_id": "from_account_id", "balance_usd": "_cash_balance_usd"}).select(
        "rollout_index", "agent_id", "from_account_id", "_cash_balance_usd"
    )
    base_proceeds = _disposition_proceeds_by_account(base_dispositions).rename({"_proceeds_usd": "_base_proceeds_usd"})
    return (
        due.join(cash, on=["rollout_index", "agent_id", "from_account_id"], how="left")
        .join(base_proceeds, on=["rollout_index", "agent_id", "from_account_id"], how="left")
        .with_columns(
            _available_before_funding_usd=pl.col("_cash_balance_usd").fill_null(0.0)
            + pl.col("_base_proceeds_usd").fill_null(0.0)
        )
        .with_columns(
            _funding_deficit_usd=pl.max_horizontal(
                0.0, pl.col("_total_due_usd") - pl.col("_available_before_funding_usd")
            )
        )
        .select(
            "rollout_index",
            "agent_id",
            "from_account_id",
            "_total_due_usd",
            "_available_before_funding_usd",
            "_funding_deficit_usd",
        )
    )


def _disposition_proceeds_by_account(dispositions: pl.DataFrame) -> pl.DataFrame:
    return (
        dispositions.group_by(["rollout_index", "agent_id", "proceeds_account_id"])
        .agg(pl.col("proceeds_usd").sum().alias("_proceeds_usd"))
        .rename({"proceeds_account_id": "from_account_id"})
    )


def _funding_dispositions_for_due_groups(
    *,
    state: StateCrossSection,
    scenario: Scenario,
    market: MarketContext,
    due_by_account: pl.DataFrame,
    base_dispositions: pl.DataFrame,
    month: int,
) -> pl.DataFrame:
    prices = market.prices_at(month)
    funding_state = _state_after_lot_dispositions(state, base_dispositions)
    blocks: list[pl.DataFrame] = []
    for policy in scenario.floor_triggered_sale_policies:
        deficit = due_by_account.filter(
            (pl.col("agent_id") == policy.agent_id)
            & (pl.col("from_account_id") == policy.account_id)
            & (pl.col("_funding_deficit_usd") > 0)
        ).select("rollout_index", pl.col("_funding_deficit_usd").alias("_remaining_deficit_usd"))
        for slot_index, asset_id in enumerate(policy.asset_preference_chain):
            if deficit.is_empty():
                break
            result = _consume_asset_for_policy(
                state=funding_state,
                policy=policy,
                asset_id=asset_id,
                slot_index=slot_index,
                prices=prices,
                deficit=deficit,
                cause_id=f"{policy.cause_id_prefix}_obligation_m{month}_{asset_id}",
                month=month,
            )
            if result.dispositions is not None and not result.dispositions.is_empty():
                blocks.append(result.dispositions)
            deficit = result.remaining_deficit
    return EVENT_FRAMES.lot_dispositions.concat(blocks)


def _state_after_lot_dispositions(state: StateCrossSection, dispositions: pl.DataFrame) -> StateCrossSection:
    if dispositions.is_empty():
        return state
    deltas = dispositions.group_by(["rollout_index", "lot_id"]).agg(pl.col("units_sold").sum().alias("_units_sold"))
    return StateCrossSection(
        cash_balances=state.cash_balances,
        asset_lots=state.asset_lots.join(deltas, on=["rollout_index", "lot_id"], how="left")
        .with_columns(remaining_quantity=pl.col("remaining_quantity") - pl.col("_units_sold").fill_null(0.0))
        .drop("_units_sold"),
        ordinary_income_ytd=state.ordinary_income_ytd,
        capital_gains_ytd=state.capital_gains_ytd,
        tax_liabilities=state.tax_liabilities,
        property_state=state.property_state,
        property_stakes=state.property_stakes,
        liabilities=state.liabilities,
        rollout_status=state.rollout_status,
    )


def _policy_funding_sources_for_obligations(scenario: Scenario, due_by_account: pl.DataFrame) -> pl.DataFrame:
    if due_by_account.is_empty():
        return due_by_account.with_columns(pl.lit("", dtype=pl.Utf8()).alias("_attempted_funding_sources"))
    policies = pl.DataFrame(
        {
            "agent_id": [policy.agent_id for policy in scenario.floor_triggered_sale_policies],
            "from_account_id": [policy.account_id for policy in scenario.floor_triggered_sale_policies],
            "_attempted_funding_sources": [
                ",".join(policy.asset_preference_chain) for policy in scenario.floor_triggered_sale_policies
            ],
        },
        schema={"agent_id": pl.Utf8(), "from_account_id": pl.Utf8(), "_attempted_funding_sources": pl.Utf8()},
    )
    if policies.is_empty():
        return due_by_account.with_columns(pl.lit("", dtype=pl.Utf8()).alias("_attempted_funding_sources"))
    return due_by_account.join(policies, on=["agent_id", "from_account_id"], how="left").with_columns(
        _attempted_funding_sources=pl.col("_attempted_funding_sources").fill_null("")
    )


def _obligation_payment_transfers(settled: pl.DataFrame) -> pl.DataFrame:
    return (
        settled.filter(pl.col("amount_paid_usd") > 0)
        .with_columns(
            pl.col("agent_id").alias("from_agent_id"),
            pl.col("amount_paid_usd").alias("amount_usd"),
            pl.lit(None, dtype=pl.Utf8()).alias("income_category"),
        )
        .pipe(EVENT_FRAMES.transfers.normalize)
    )


def _obligation_failure_events(settled: pl.DataFrame, month: int) -> pl.DataFrame:
    return (
        settled.filter(pl.col("shortfall_usd") > 0)
        .with_columns(
            pl.lit(month, dtype=pl.Int64()).alias("month_index"),
            pl.concat_str([pl.col("obligation_id"), pl.lit("_failure")]).alias("cause_id"),
            pl.col("shortfall_usd").alias("deficit_usd"),
        )
        .pipe(EVENT_FRAMES.rollout_failures.normalize)
    )


def _paid_mortgage_payment_events(
    mortgage_payments: pl.DataFrame, obligation_settlements: pl.DataFrame
) -> pl.DataFrame:
    if mortgage_payments.is_empty() or obligation_settlements.is_empty():
        return EVENT_FRAMES.mortgage_payments.empty()
    paid = obligation_settlements.filter(
        (pl.col("obligation_type") == "mortgage_payment") & (pl.col("shortfall_usd") == 0)
    ).select("rollout_index", pl.col("obligation_id").alias("cause_id"))
    return EVENT_FRAMES.mortgage_payments.normalize(
        mortgage_payments.join(paid, on=["rollout_index", "cause_id"], how="inner")
    )


def _paid_tax_settlement_events(settlements: pl.DataFrame, obligation_settlements: pl.DataFrame) -> pl.DataFrame:
    if settlements.is_empty():
        return EVENT_FRAMES.tax_settlements.empty()
    failed_tax = (
        obligation_settlements.filter(
            pl.col("obligation_type").is_in(["estimated_tax", "tax_true_up"]) & (pl.col("shortfall_usd") > 0)
        )
        .select("rollout_index", "agent_id")
        .unique()
        .with_columns(pl.lit(True).alias("_failed_tax_payment"))
    )
    return (
        settlements.join(failed_tax, on=["rollout_index", "agent_id"], how="left")
        .filter(~pl.col("_failed_tax_payment").fill_null(False))
        .drop("_failed_tax_payment")
        .pipe(EVENT_FRAMES.tax_settlements.normalize)
    )


def _emit_lot_dispositions(
    state: StateCrossSection, scenario: Scenario, market: MarketContext, month: int
) -> pl.DataFrame:
    """Emit `LotDisposition` rows for every scheduled asset sale at
    this month. Each sale is FIFO-resolved against the agent's
    current lots of the asset; the same resolution applies
    per-rollout via polars window functions over `rollout_index`.

    When the sale supplies an explicit `price_per_unit_usd` that
    price applies uniformly across rollouts; otherwise the price
    comes from the exogenous trajectory bundle's per-rollout
    per-month curve."""
    sales = [s for s in scenario.scheduled_asset_sales if s.month == month]
    if not sales:
        return EVENT_FRAMES.lot_dispositions.empty()
    prices_at_month = market.prices_at(month)
    blocks = [_fifo_dispositions_for_sale(state, sale, prices_at_month, month) for sale in sales]
    return EVENT_FRAMES.lot_dispositions.concat(blocks)


def _fifo_dispositions_for_sale(
    state: StateCrossSection, sale: ScheduledAssetSale, prices_at_month: pl.DataFrame, month: int
) -> pl.DataFrame:
    """Vectorized FIFO consumption of one sale across all rollouts.

    Within each rollout the lots of the matching `(agent_id,
    asset_id)` are ordered by `purchase_month_index` ascending; the
    sale eats from the oldest forward. A lot's `units_sold` is
    `clip(sale.quantity - prev_cumulative_remaining, 0,
    remaining_quantity)`. The result is one disposition row per
    consumed lot per rollout.

    Pricing: if `sale.price_per_unit_usd` is set it's used as a
    scalar; otherwise `prices_at_month` is joined by
    `(rollout_index, asset_id)` so each rollout gets its own
    market-derived price."""
    candidates = state.asset_lots.filter(
        (pl.col("agent_id") == sale.agent_id)
        & (pl.col("asset_id") == sale.asset_id)
        & (pl.col("remaining_quantity") > 0)
    )
    if candidates.is_empty():
        return EVENT_FRAMES.lot_dispositions.empty()
    priced = _attach_unit_price(candidates, sale, prices_at_month)
    ordered = priced.sort(["rollout_index", "purchase_month_index", "lot_id"])
    with_cum = ordered.with_columns(
        _prev_cum_remaining=(
            pl.col("remaining_quantity").cum_sum().over("rollout_index") - pl.col("remaining_quantity")
        )
    )
    sized = with_cum.with_columns(
        _units_from_lot=pl.min_horizontal(
            pl.col("remaining_quantity"),
            pl.max_horizontal(pl.lit(0.0), pl.lit(sale.quantity) - pl.col("_prev_cum_remaining")),
        )
    )
    consumed = sized.filter(pl.col("_units_from_lot") > 0)
    if consumed.is_empty():
        return EVENT_FRAMES.lot_dispositions.empty()
    return consumed.with_columns(
        pl.lit(month, dtype=pl.Int64()).alias("month_index"),
        pl.lit(sale.cause_id, dtype=pl.Utf8()).alias("cause_id"),
        pl.col("_units_from_lot").alias("units_sold"),
        (pl.col("_units_from_lot") * pl.col("cost_basis_per_unit_usd")).alias("cost_basis_consumed_usd"),
        (pl.col("_units_from_lot") * pl.col("_unit_price")).alias("proceeds_usd"),
        pl.lit(sale.proceeds_account_id, dtype=pl.Utf8()).alias("proceeds_account_id"),
    ).pipe(EVENT_FRAMES.lot_dispositions.normalize)


def _attach_unit_price(lots: pl.DataFrame, sale: ScheduledAssetSale, prices_at_month: pl.DataFrame) -> pl.DataFrame:
    """Add a `_unit_price` column to the candidate lots. Scalar
    price (configured on the sale) is broadcast across rollouts;
    market-derived price is joined per `(rollout_index, asset_id)`."""
    if sale.price_per_unit_usd is not None:
        return lots.with_columns(pl.lit(sale.price_per_unit_usd, dtype=pl.Float64()).alias("_unit_price"))
    prices_for_asset = prices_at_month.filter(pl.col("asset_id") == sale.asset_id).rename(
        {"price_per_unit_usd": "_unit_price"}
    )
    return lots.join(prices_for_asset.select("rollout_index", "_unit_price"), on="rollout_index", how="left")


def _emit_floor_triggered_sales(
    state: StateCrossSection, scenario: Scenario, market: MarketContext, month: int
) -> pl.DataFrame:
    """For every `FloorTriggeredSalePolicy`, find rollouts whose
    monitored account is below the floor and emit FIFO lot
    dispositions walking the asset preference chain until either
    the deficit is covered or the chain is exhausted. Vectorized
    over rollouts; Python-loops only over asset slots (typically
    3-5 entries)."""
    if not scenario.floor_triggered_sale_policies:
        return EVENT_FRAMES.lot_dispositions.empty()
    prices = market.prices_at(month)
    active_rollouts = state.rollout_status.filter(pl.col("status") == "active").select("rollout_index")
    blocks: list[pl.DataFrame] = []
    for policy in scenario.floor_triggered_sale_policies:
        blocks.extend(_dispositions_for_policy(state, policy, prices, active_rollouts, month))
    return EVENT_FRAMES.lot_dispositions.concat(blocks)


def _dispositions_for_policy(
    state: StateCrossSection,
    policy: FloorTriggeredSalePolicy,
    prices: pl.DataFrame,
    active_rollouts: pl.DataFrame,
    month: int,
) -> list[pl.DataFrame]:
    """Resolve one policy across the rollout column. Returns a list
    of disposition blocks (one per asset slot consumed)."""
    cash = state.cash_balances.filter(
        (pl.col("agent_id") == policy.agent_id) & (pl.col("account_id") == policy.account_id)
    ).select("rollout_index", pl.col("balance_usd").alias("_balance_usd"))
    deficit = (
        cash.join(active_rollouts, on="rollout_index", how="inner")
        .with_columns(
            _remaining_deficit_usd=pl.lit(policy.floor_usd + policy.replenish_buffer_usd) - pl.col("_balance_usd")
        )
        .filter(pl.col("_remaining_deficit_usd") > 0)
        .select("rollout_index", "_remaining_deficit_usd")
    )
    if deficit.is_empty():
        return []
    blocks: list[pl.DataFrame] = []
    for slot_index, asset_id in enumerate(policy.asset_preference_chain):
        if deficit.is_empty():
            break
        cause_id = f"{policy.cause_id_prefix}_m{month}_{asset_id}"
        result = _consume_asset_for_policy(
            state=state,
            policy=policy,
            asset_id=asset_id,
            slot_index=slot_index,
            prices=prices,
            deficit=deficit,
            cause_id=cause_id,
            month=month,
        )
        if result.dispositions is not None and not result.dispositions.is_empty():
            blocks.append(result.dispositions)
        deficit = result.remaining_deficit
    return blocks


@dataclass(frozen=True)
class _PolicyAssetResult:
    """Output of consuming one asset within a policy: the lot
    dispositions emitted for the asset plus the residual deficit
    after this asset's sale (to feed the next asset slot)."""

    dispositions: pl.DataFrame | None
    remaining_deficit: pl.DataFrame


def _consume_asset_for_policy(
    *,
    state: StateCrossSection,
    policy: FloorTriggeredSalePolicy,
    asset_id: str,
    slot_index: int,
    prices: pl.DataFrame,
    deficit: pl.DataFrame,
    cause_id: str,
    month: int,
) -> _PolicyAssetResult:
    """Walk the agent's lots of `asset_id` in FIFO order to cover
    as much of each rollout's remaining deficit as the asset
    supports. Decrement the deficit by the dollars actually
    realized. Returns the new disposition frame and an updated
    deficit frame for the next asset slot."""
    asset_price = prices.filter(pl.col("asset_id") == asset_id).select(
        "rollout_index", pl.col("price_per_unit_usd").alias("_unit_price")
    )
    lots = (
        state.asset_lots.filter(
            (pl.col("agent_id") == policy.agent_id)
            & (pl.col("asset_id") == asset_id)
            & (pl.col("remaining_quantity") > 0)
        )
        .join(asset_price, on="rollout_index", how="left")
        .join(deficit, on="rollout_index", how="inner")
    )
    if lots.is_empty():
        return _PolicyAssetResult(dispositions=None, remaining_deficit=deficit)
    ordered = lots.sort(["rollout_index", "purchase_month_index", "lot_id"])
    with_cum = ordered.with_columns(
        _prev_cum_dollars=(
            (pl.col("remaining_quantity") * pl.col("_unit_price")).cum_sum().over("rollout_index")
            - (pl.col("remaining_quantity") * pl.col("_unit_price"))
        )
    )
    sized = with_cum.with_columns(
        _dollars_from_lot=pl.min_horizontal(
            pl.col("remaining_quantity") * pl.col("_unit_price"),
            pl.max_horizontal(pl.lit(0.0), pl.col("_remaining_deficit_usd") - pl.col("_prev_cum_dollars")),
        )
    )
    consumed = sized.filter(pl.col("_dollars_from_lot") > 0).with_columns(
        _units_from_lot=pl.col("_dollars_from_lot") / pl.col("_unit_price")
    )
    if consumed.is_empty():
        return _PolicyAssetResult(dispositions=None, remaining_deficit=deficit)
    dispositions = consumed.with_columns(
        pl.lit(month, dtype=pl.Int64()).alias("month_index"),
        pl.lit(cause_id, dtype=pl.Utf8()).alias("cause_id"),
        pl.col("_units_from_lot").alias("units_sold"),
        (pl.col("_units_from_lot") * pl.col("cost_basis_per_unit_usd")).alias("cost_basis_consumed_usd"),
        pl.col("_dollars_from_lot").alias("proceeds_usd"),
        pl.lit(policy.account_id, dtype=pl.Utf8()).alias("proceeds_account_id"),
    ).pipe(EVENT_FRAMES.lot_dispositions.normalize)
    _ = slot_index  # reserved for future use (e.g. partial-fill accounting)
    realized_per_rollout = consumed.group_by("rollout_index").agg(
        pl.col("_dollars_from_lot").sum().alias("_realized_usd")
    )
    new_deficit = (
        deficit.join(realized_per_rollout, on="rollout_index", how="left")
        .with_columns(_remaining_deficit_usd=pl.col("_remaining_deficit_usd") - pl.col("_realized_usd").fill_null(0.0))
        .filter(pl.col("_remaining_deficit_usd") > 0)
        .select("rollout_index", "_remaining_deficit_usd")
    )
    return _PolicyAssetResult(dispositions=dispositions, remaining_deficit=new_deficit)


def _emit_rollout_failures(
    *,
    state: StateCrossSection,
    scenario: Scenario,
    policy_dispositions: pl.DataFrame,
    transfers: pl.DataFrame,
    month: int,
) -> pl.DataFrame:
    """Flag any active rollout whose monitored cash account is
    still below 0 after the floor-triggered sales and due-now
    transfers in this phase have fired. Cash on the post-phase-1
    state is in `state.cash_balances`; this phase's dispositions
    and transfers haven't been applied yet, so project them before
    checking the floor."""
    if not scenario.floor_triggered_sale_policies:
        return EVENT_FRAMES.rollout_failures.empty()
    active_rollouts = state.rollout_status.filter(pl.col("status") == "active").select("rollout_index")
    blocks: list[pl.DataFrame] = []
    for policy in scenario.floor_triggered_sale_policies:
        policy_proceeds = (
            policy_dispositions.filter(
                (pl.col("agent_id") == policy.agent_id) & (pl.col("proceeds_account_id") == policy.account_id)
            )
            .group_by("rollout_index")
            .agg(pl.col("proceeds_usd").sum().alias("_proceeds"))
        )
        transfer_deltas = _transfer_delta_for_account(transfers, policy.agent_id, policy.account_id)
        pre_failure_cash = (
            state.cash_balances.filter(
                (pl.col("agent_id") == policy.agent_id) & (pl.col("account_id") == policy.account_id)
            )
            .select("rollout_index", pl.col("balance_usd").alias("_balance"))
            .join(policy_proceeds, on="rollout_index", how="left")
            .join(transfer_deltas, on="rollout_index", how="left")
            .with_columns(
                _projected=pl.col("_balance")
                + pl.col("_proceeds").fill_null(0.0)
                + pl.col("_transfer_delta").fill_null(0.0)
            )
            .join(active_rollouts, on="rollout_index", how="inner")
            .filter(pl.col("_projected") < 0)
        )
        if pre_failure_cash.is_empty():
            continue
        blocks.append(
            pre_failure_cash.with_columns(
                pl.lit(month, dtype=pl.Int64()).alias("month_index"),
                pl.lit(f"{policy.cause_id_prefix}_failure_m{month}", dtype=pl.Utf8()).alias("cause_id"),
                pl.lit(policy.agent_id, dtype=pl.Utf8()).alias("agent_id"),
                deficit_usd=-pl.col("_projected"),
                obligation_id=pl.lit(None, dtype=pl.Utf8()),
                obligation_type=pl.lit(None, dtype=pl.Utf8()),
                amount_due_usd=-pl.col("_projected"),
                amount_paid_usd=pl.lit(0.0, dtype=pl.Float64()),
                shortfall_usd=-pl.col("_projected"),
                attempted_funding_sources=pl.lit(",".join(policy.asset_preference_chain), dtype=pl.Utf8()),
            ).pipe(EVENT_FRAMES.rollout_failures.normalize)
        )
    return EVENT_FRAMES.rollout_failures.concat(blocks)


def _transfer_delta_for_account(transfers: pl.DataFrame, agent_id: str, account_id: str) -> pl.DataFrame:
    outgoing = (
        transfers.filter((pl.col("from_agent_id") == agent_id) & (pl.col("from_account_id") == account_id))
        .group_by("rollout_index")
        .agg((-pl.col("amount_usd").sum()).alias("_outgoing"))
    )
    incoming = (
        transfers.filter((pl.col("to_agent_id") == agent_id) & (pl.col("to_account_id") == account_id))
        .group_by("rollout_index")
        .agg(pl.col("amount_usd").sum().alias("_incoming"))
    )
    return (
        outgoing.join(incoming, on="rollout_index", how="full", coalesce=True)
        .with_columns(_transfer_delta=pl.col("_outgoing").fill_null(0.0) + pl.col("_incoming").fill_null(0.0))
        .select("rollout_index", "_transfer_delta")
    )


def _is_year_end(month: int) -> bool:
    """Tax years are calendar-year-aligned at spike 1: the year
    ends at month index 11, 23, 35, …"""
    return month % 12 == 11


def _emit_tax_payment_obligations(
    *, state: StateCrossSection, profiles: list[TaxProfile], month: int
) -> _TaxPaymentObligationEvents:
    """Emit estimated-tax obligations and liability-settlement candidates.

    Q1/Q2/Q3 estimates are cash payments only: the tax liability for
    that tax year does not exist yet. The following January emits the
    Q4/true-up obligations and a tax-settlement candidate that applies
    the full year's paid tax against the already-accrued liability once
    the due-now settlement succeeds.
    """
    if not profiles:
        return _empty_tax_payment_obligation_events()
    obligation_blocks: list[pl.DataFrame] = []
    settlement_blocks: list[pl.DataFrame] = []
    quarter = _estimated_tax_quarter(month)
    for profile in profiles:
        if quarter in {1, 2, 3}:
            amount = profile.prior_year_tax_usd / 4.0
            if amount <= 0:
                continue
            amounts = state.rollout_status.select("rollout_index").with_columns(
                pl.lit(amount, dtype=pl.Float64()).alias("amount_usd")
            )
            tax_year = month // 12
            obligation_blocks.append(
                _tax_payment_obligation_block(
                    amounts=amounts,
                    profile=profile,
                    month=month,
                    cause_id=f"{profile.agent_id}_estimated_tax_q{quarter}_y{tax_year}",
                    obligation_type="estimated_tax",
                )
            )
        elif quarter == 4:
            tax_year = month // 12 - 1
            if tax_year < 0:
                continue
            final_events = _final_estimated_and_true_up_events(
                state=state, profile=profile, month=month, tax_year=tax_year
            )
            obligation_blocks.append(final_events.obligation_accruals)
            settlement_blocks.append(final_events.settlements)
    return _TaxPaymentObligationEvents(
        obligation_accruals=EVENT_FRAMES.obligation_accruals.concat(obligation_blocks),
        settlements=EVENT_FRAMES.tax_settlements.concat(settlement_blocks),
    )


def _empty_tax_payment_obligation_events() -> _TaxPaymentObligationEvents:
    return _TaxPaymentObligationEvents(
        obligation_accruals=EVENT_FRAMES.obligation_accruals.empty(), settlements=EVENT_FRAMES.tax_settlements.empty()
    )


def _estimated_tax_quarter(month: int) -> int | None:
    """Calendar-month markers in a zero-based monthly simulation.

    Month 0 is January. Estimated payments are emitted in April,
    June, September, and the following January."""
    month_in_year = month % 12
    if month_in_year == 3:
        return 1
    if month_in_year == 5:
        return 2
    if month_in_year == 8:
        return 3
    if month_in_year == 0 and month > 0:
        return 4
    return None


def _final_estimated_and_true_up_events(
    *, state: StateCrossSection, profile: TaxProfile, month: int, tax_year: int
) -> _TaxPaymentObligationEvents:
    """Return Q4 estimated, true-up, and settlement events.

    `prior_year_tax_usd` is the aggregate safe-harbor target for
    the profile. Year-end accruals remain per jurisdiction; the cash
    payment is aggregate, and the settlement applies against all
    outstanding jurisdiction rows for the same tax year."""
    actual = _actual_tax_by_rollout(state.tax_liabilities, profile=profile, tax_year=tax_year)
    if actual.is_empty():
        return _empty_tax_payment_obligation_events()
    safe_harbor_total = pl.min_horizontal(
        pl.lit(profile.prior_year_tax_usd, dtype=pl.Float64()), pl.col("_actual_tax_usd")
    )
    paid_before_q4 = profile.prior_year_tax_usd * 0.75
    payments = actual.with_columns(
        _q4_amount_usd=pl.max_horizontal(pl.lit(0.0), safe_harbor_total - pl.lit(paid_before_q4)),
        _true_up_amount_usd=pl.max_horizontal(pl.lit(0.0), pl.col("_actual_tax_usd") - safe_harbor_total),
    )
    q4 = payments.select("rollout_index", pl.col("_q4_amount_usd").alias("amount_usd"))
    true_up = payments.select("rollout_index", pl.col("_true_up_amount_usd").alias("amount_usd"))
    settlement = payments.select("rollout_index", pl.col("_actual_tax_usd").alias("amount_usd"))
    return _TaxPaymentObligationEvents(
        obligation_accruals=EVENT_FRAMES.obligation_accruals.concat(
            [
                _tax_payment_obligation_block(
                    amounts=q4,
                    profile=profile,
                    month=month,
                    cause_id=f"{profile.agent_id}_estimated_tax_q4_y{tax_year}",
                    obligation_type="estimated_tax",
                ),
                _tax_payment_obligation_block(
                    amounts=true_up,
                    profile=profile,
                    month=month,
                    cause_id=f"{profile.agent_id}_tax_true_up_y{tax_year}",
                    obligation_type="tax_true_up",
                ),
            ]
        ),
        settlements=_tax_settlement_block(
            amounts=settlement,
            profile=profile,
            month=month,
            tax_year=tax_year,
            cause_id=f"{profile.agent_id}_tax_settlement_y{tax_year}",
        ),
    )


def _actual_tax_by_rollout(tax_liabilities: pl.DataFrame, *, profile: TaxProfile, tax_year: int) -> pl.DataFrame:
    """Sum year-end tax accruals across jurisdictions for one profile."""
    tax_year_end_month = tax_year * 12 + 11
    return (
        tax_liabilities.filter(
            (pl.col("agent_id") == profile.agent_id) & (pl.col("tax_year_end_month") == tax_year_end_month)
        )
        .group_by("rollout_index")
        .agg(pl.col("amount_owed_usd").sum().alias("_actual_tax_usd"))
    )


def _tax_payment_obligation_block(
    *, amounts: pl.DataFrame, profile: TaxProfile, month: int, cause_id: str, obligation_type: str
) -> pl.DataFrame:
    """Project per-rollout tax payment amounts into obligations."""
    return (
        amounts.filter(pl.col("amount_usd") > 0)
        .with_columns(
            pl.lit(month, dtype=pl.Int64()).alias("month_index"),
            pl.lit(cause_id, dtype=pl.Utf8()).alias("cause_id"),
            pl.lit(cause_id, dtype=pl.Utf8()).alias("obligation_id"),
            pl.lit(obligation_type, dtype=pl.Utf8()).alias("obligation_type"),
            pl.lit(profile.agent_id, dtype=pl.Utf8()).alias("agent_id"),
            pl.lit(profile.payment_account_id, dtype=pl.Utf8()).alias("from_account_id"),
            pl.lit(profile.tax_authority_agent_id, dtype=pl.Utf8()).alias("to_agent_id"),
            pl.lit(profile.tax_authority_account_id, dtype=pl.Utf8()).alias("to_account_id"),
            pl.col("amount_usd").alias("amount_due_usd"),
        )
        .pipe(EVENT_FRAMES.obligation_accruals.normalize)
    )


def _tax_settlement_block(
    *, amounts: pl.DataFrame, profile: TaxProfile, month: int, tax_year: int, cause_id: str
) -> pl.DataFrame:
    """Project per-rollout settlement amounts into liability rows."""
    tax_year_end_month = tax_year * 12 + 11
    return (
        amounts.filter(pl.col("amount_usd") > 0)
        .with_columns(
            pl.lit(month, dtype=pl.Int64()).alias("month_index"),
            pl.lit(cause_id, dtype=pl.Utf8()).alias("cause_id"),
            pl.lit(profile.agent_id, dtype=pl.Utf8()).alias("agent_id"),
            pl.lit(tax_year_end_month, dtype=pl.Int64()).alias("tax_year_end_month"),
        )
        .pipe(EVENT_FRAMES.tax_settlements.normalize)
    )


def _emit_year_end_tax_events(
    *,
    state: StateCrossSection,
    scenario: Scenario,
    jurisdictions: dict[str, Jurisdiction],
    month: int,
    transfers: pl.DataFrame,
    dispositions: pl.DataFrame,
) -> _TaxYearEvents:
    """At year-end emit tax accruals plus audit breakdown rows.

    Federal tax = ordinary_bracket_walk (ordinary_income + STCG -
    std_ded) + LTCG_bracket_walk(LTCG stacked above
    ordinary_taxable). California tax = ordinary bracket walk on
    (ordinary_income + LTCG + STCG - std_ded) because CA does not
    have a separate LTCG schedule.

    Like ordinary income, capital gains are summed as `state YTD +
    this-month's dispositions` since `apply_events` will produce
    that same YTD before the year closes."""
    if not _is_year_end(month) or not scenario.tax_profiles:
        return _empty_tax_year_events()
    eoy = _compute_end_of_year_taxable_components(state, transfers, dispositions, scenario.tax_profiles, month)
    events = [_tax_events_for_profile(profile, eoy, jurisdictions, month) for profile in scenario.tax_profiles]
    accrual_blocks = [event.accruals for event in events]
    breakdown_blocks = [event.breakdowns for event in events]
    return _TaxYearEvents(
        accruals=EVENT_FRAMES.tax_accruals.concat(accrual_blocks),
        breakdowns=EVENT_FRAMES.tax_breakdowns.concat(breakdown_blocks),
    )


def _empty_tax_year_events() -> _TaxYearEvents:
    return _TaxYearEvents(accruals=EVENT_FRAMES.tax_accruals.empty(), breakdowns=EVENT_FRAMES.tax_breakdowns.empty())


def _compute_end_of_year_taxable_components(
    state: StateCrossSection,
    transfers: pl.DataFrame,
    dispositions: pl.DataFrame,
    profiles: list[TaxProfile],
    month: int,
) -> pl.DataFrame:
    """Return one row per (rollout, agent) with columns
    `ordinary_income_usd`, `ltcg_usd`, `stcg_usd` — the end-of-year
    totals matching what apply_events will materialize. Computed
    as `pre-month state YTD + this-month's emitted events` so the
    step can compose the tax accrual without round-tripping."""
    taxed_agents = [p.agent_id for p in profiles]
    pre_ord = state.ordinary_income_ytd.filter(pl.col("agent_id").is_in(taxed_agents))
    pre_cg = state.capital_gains_ytd.filter(pl.col("agent_id").is_in(taxed_agents))
    pre_ltcg = pre_cg.filter(pl.col("classification") == "ltcg").select(
        "rollout_index", "agent_id", pl.col("gain_usd").alias("ltcg_usd")
    )
    pre_stcg = pre_cg.filter(pl.col("classification") == "stcg").select(
        "rollout_index", "agent_id", pl.col("gain_usd").alias("stcg_usd")
    )
    this_month_ord = (
        transfers.filter((pl.col("income_category") == "ordinary") & pl.col("to_agent_id").is_in(taxed_agents))
        .group_by(["rollout_index", "to_agent_id"])
        .agg(pl.col("amount_usd").sum().alias("_this_month_ord"))
        .rename({"to_agent_id": "agent_id"})
    )
    classified_dispositions = dispositions.filter(pl.col("agent_id").is_in(taxed_agents)).with_columns(
        gain_usd=pl.col("proceeds_usd") - pl.col("cost_basis_consumed_usd"),
        is_ltcg=(pl.lit(month) - pl.col("purchase_month_index")) >= 12,
    )
    this_month_ltcg = (
        classified_dispositions.filter(pl.col("is_ltcg"))
        .group_by(["rollout_index", "agent_id"])
        .agg(pl.col("gain_usd").sum().alias("_this_month_ltcg"))
    )
    this_month_stcg = (
        classified_dispositions.filter(~pl.col("is_ltcg"))
        .group_by(["rollout_index", "agent_id"])
        .agg(pl.col("gain_usd").sum().alias("_this_month_stcg"))
    )
    return (
        pre_ord.join(this_month_ord, on=["rollout_index", "agent_id"], how="left")
        .with_columns(ordinary_income_usd=pl.col("ordinary_income_usd") + pl.col("_this_month_ord").fill_null(0.0))
        .drop("_this_month_ord")
        .join(pre_ltcg, on=["rollout_index", "agent_id"], how="left")
        .join(this_month_ltcg, on=["rollout_index", "agent_id"], how="left")
        .with_columns(ltcg_usd=pl.col("ltcg_usd").fill_null(0.0) + pl.col("_this_month_ltcg").fill_null(0.0))
        .drop("_this_month_ltcg")
        .join(pre_stcg, on=["rollout_index", "agent_id"], how="left")
        .join(this_month_stcg, on=["rollout_index", "agent_id"], how="left")
        .with_columns(stcg_usd=pl.col("stcg_usd").fill_null(0.0) + pl.col("_this_month_stcg").fill_null(0.0))
        .drop("_this_month_stcg")
    )


def _tax_events_for_profile(
    profile: TaxProfile, eoy: pl.DataFrame, jurisdictions: dict[str, Jurisdiction], month: int
) -> _TaxYearEvents:
    """Compute accrual and breakdown rows for one tax profile."""
    eoy_rows = eoy.filter(pl.col("agent_id") == profile.agent_id).sort("rollout_index")
    if eoy_rows.is_empty():
        return _empty_tax_year_events()
    rollout_idx = eoy_rows.get_column("rollout_index").to_numpy()
    ordinary = eoy_rows.get_column("ordinary_income_usd").to_numpy()
    ltcg = eoy_rows.get_column("ltcg_usd").to_numpy()
    stcg = eoy_rows.get_column("stcg_usd").to_numpy()
    accrual_blocks = []
    breakdown_blocks = []
    for jurisdiction_id in profile.jurisdiction_ids:
        jurisdiction = jurisdictions[jurisdiction_id]
        deduction = jurisdiction.standard_deduction[profile.filing_status]
        ord_brackets = jurisdiction.ordinary_income_brackets[profile.filing_status]
        if jurisdiction.ltcg_brackets is not None:
            ltcg_brackets = jurisdiction.ltcg_brackets[profile.filing_status]
            ordinary_taxable = np.maximum(ordinary + stcg - deduction, 0.0)
            capital_gain_taxable = ltcg
            ordinary_tax = apply_brackets(ordinary_taxable, ord_brackets)
            capital_gain_tax = apply_ltcg_brackets(ltcg, ordinary_taxable, ltcg_brackets)
            tax = ordinary_tax + capital_gain_tax
        else:
            ordinary_taxable = np.maximum(ordinary + ltcg + stcg - deduction, 0.0)
            capital_gain_taxable = np.zeros_like(ordinary)
            ordinary_tax = apply_brackets(ordinary_taxable, ord_brackets)
            capital_gain_tax = np.zeros_like(ordinary)
            tax = ordinary_tax
        cause_id = f"{profile.agent_id}_{jurisdiction_id}_year_end_accrual_m{month}"
        accrual_blocks.append(
            pl.DataFrame(
                {
                    "rollout_index": rollout_idx,
                    "month_index": np.full_like(rollout_idx, month),
                    "cause_id": [cause_id] * len(rollout_idx),
                    "agent_id": [profile.agent_id] * len(rollout_idx),
                    "jurisdiction_id": [jurisdiction_id] * len(rollout_idx),
                    "tax_year_end_month": np.full_like(rollout_idx, month),
                    "amount_usd": tax,
                },
                schema=EVENT_FRAMES.tax_accruals.schema,
            )
        )
        breakdown_blocks.append(
            pl.DataFrame(
                {
                    "rollout_index": rollout_idx,
                    "month_index": np.full_like(rollout_idx, month),
                    "cause_id": [cause_id] * len(rollout_idx),
                    "agent_id": [profile.agent_id] * len(rollout_idx),
                    "jurisdiction_id": [jurisdiction_id] * len(rollout_idx),
                    "tax_year_end_month": np.full_like(rollout_idx, month),
                    "ordinary_income_usd": ordinary,
                    "ltcg_usd": ltcg,
                    "stcg_usd": stcg,
                    "standard_deduction_usd": np.full(len(rollout_idx), deduction, dtype=float),
                    "ordinary_taxable_usd": ordinary_taxable,
                    "capital_gain_taxable_usd": capital_gain_taxable,
                    "ordinary_tax_usd": ordinary_tax,
                    "capital_gain_tax_usd": capital_gain_tax,
                    "total_tax_usd": tax,
                },
                schema=EVENT_FRAMES.tax_breakdowns.schema,
            )
        )
    return _TaxYearEvents(
        accruals=EVENT_FRAMES.tax_accruals.concat(accrual_blocks),
        breakdowns=EVENT_FRAMES.tax_breakdowns.concat(breakdown_blocks),
    )
