"""Forward simulation loop.

`simulate(scenario, rollout_count) → SimulationRun` runs the
per-month step over the scenario's horizon and produces the
state-over-time long-form frames + the event log.

The loop carries `state_t` (the polars cross-section, no
month_index column) forward. Each iteration:

  events_t = step_emit_events(state_t, scenario, market,
                              jurisdictions, month, rollout_count)
  state_t = apply_events(state_t, events_t)

`apply_events` is the only state-mutation point. The replay
invariant holds by construction: at any month M, `state_t` equals
`apply_events(initial_state, events_log.filter(month < M))`.

The state-over-time frames in the returned `SimulationRun` are
the concatenation of the per-month cross-sections with
`month_index` injected as a column.
"""

from __future__ import annotations

import polars as pl

from augur.sim.apply import apply_events
from augur.sim.events import (
    ASSET_PURCHASE_EVENT_SCHEMA,
    LOT_DISPOSITION_EVENT_SCHEMA,
    MORTGAGE_ORIGINATION_EVENT_SCHEMA,
    MORTGAGE_PAYMENT_EVENT_SCHEMA,
    PROPERTY_PURCHASE_EVENT_SCHEMA,
    ROLLOUT_FAILURE_EVENT_SCHEMA,
    TAX_ACCRUAL_EVENT_SCHEMA,
    TAX_BREAKDOWN_EVENT_SCHEMA,
    TAX_SETTLEMENT_EVENT_SCHEMA,
    TRANSFER_EVENT_SCHEMA,
    EventLog,
    concat_event_frames,
)
from augur.sim.jurisdictions import Jurisdiction, load_jurisdiction
from augur.sim.locations import Location, load_location
from augur.sim.market import materialize_market
from augur.sim.run import SimulationRun
from augur.sim.scenario import Scenario
from augur.sim.state import (
    ASSET_LOT_SCHEMA,
    CAPITAL_GAINS_YTD_SCHEMA,
    CASH_BALANCES_SCHEMA,
    LIABILITY_SCHEMA,
    ORDINARY_INCOME_YTD_SCHEMA,
    PROPERTY_STAKE_SCHEMA,
    PROPERTY_STATE_SCHEMA,
    ROLLOUT_STATUS_SCHEMA,
    TAX_LIABILITIES_SCHEMA,
    StateCrossSection,
)
from augur.sim.step import step_emit_policy_events, step_emit_scheduled_events


def simulate(scenario: Scenario, *, rollout_count: int) -> SimulationRun:
    if rollout_count <= 0:
        msg = f"rollout_count must be positive; got {rollout_count}"
        raise ValueError(msg)
    market = materialize_market(
        scenario.market, rollout_count=rollout_count, horizon_months=int(scenario.horizon_months)
    )
    jurisdictions = _load_jurisdictions_for(scenario)
    locations = _load_locations_for(scenario)
    state_t = _initial_state(scenario, rollout_count)
    cross_sections: list[StateCrossSection] = [state_t]
    events_by_month: list[EventLog] = []
    for month in range(int(scenario.horizon_months)):
        events_p1 = step_emit_scheduled_events(
            state=state_t,
            scenario=scenario,
            market=market,
            jurisdictions=jurisdictions,
            locations=locations,
            month=month,
            rollout_count=rollout_count,
        )
        state_t = apply_events(state_t, events_p1)
        events_p2 = step_emit_policy_events(state=state_t, scenario=scenario, market=market, month=month)
        state_t = apply_events(state_t, events_p2)
        cross_sections.append(state_t)
        events_by_month.append(_merge_event_logs(events_p1, events_p2))
    return SimulationRun(
        cash_balances=_stack_cash_balances(cross_sections),
        asset_lots=_stack_asset_lots(cross_sections),
        ordinary_income_ytd=_stack_income_ytd(cross_sections),
        capital_gains_ytd=_stack_capital_gains(cross_sections),
        tax_liabilities=_stack_tax_liabilities(cross_sections),
        property_state=_stack_property_state(cross_sections),
        property_stakes=_stack_property_stakes(cross_sections),
        liabilities=_stack_liabilities(cross_sections),
        rollout_status_history=_stack_rollout_status(cross_sections),
        rollout_status=cross_sections[-1].rollout_status,
        market_prices=market.prices,
        events_log=_concat_events(events_by_month),
    )


def _load_jurisdictions_for(scenario: Scenario) -> dict[str, Jurisdiction]:
    """Load every jurisdiction referenced by any tax profile.
    Loaded once at sim start; the step closes over the dict."""
    ids = {jid for profile in scenario.tax_profiles for jid in profile.jurisdiction_ids}
    return {jid: load_jurisdiction(jid) for jid in ids}


def _load_locations_for(scenario: Scenario) -> dict[str, Location]:
    ids = {purchase.location_id for purchase in scenario.scheduled_property_purchases}
    return {location_id: load_location(location_id) for location_id in ids}


def _initial_state(scenario: Scenario, rollout_count: int) -> StateCrossSection:
    """Build the initial (month-0) state cross-section from the
    scenario's `initial_cash` and `initial_lots`. Each entry expands
    to one row per rollout via a cross join — no Python loop over
    rollouts. Pre-horizon `purchase_month_index` (e.g. -24 for a lot
    bought before the sim) is preserved as-is for later holding-
    period classification."""
    rollouts = pl.DataFrame({"rollout_index": list(range(rollout_count))}, schema={"rollout_index": pl.Int64()})
    cash = _initial_cash(scenario, rollouts)
    asset_lots = _initial_asset_lots(scenario, rollouts)
    ordinary_income_ytd = _initial_ordinary_income_ytd(scenario, rollouts)
    capital_gains_ytd = pl.DataFrame(schema=CAPITAL_GAINS_YTD_SCHEMA)
    tax_liabilities = pl.DataFrame(schema=TAX_LIABILITIES_SCHEMA)
    property_state = pl.DataFrame(schema=PROPERTY_STATE_SCHEMA)
    property_stakes = pl.DataFrame(schema=PROPERTY_STAKE_SCHEMA)
    liabilities = pl.DataFrame(schema=LIABILITY_SCHEMA)
    rollout_status = _initial_rollout_status(rollouts)
    return StateCrossSection(
        cash_balances=cash,
        asset_lots=asset_lots,
        ordinary_income_ytd=ordinary_income_ytd,
        capital_gains_ytd=capital_gains_ytd,
        tax_liabilities=tax_liabilities,
        property_state=property_state,
        property_stakes=property_stakes,
        liabilities=liabilities,
        rollout_status=rollout_status,
    )


def _initial_rollout_status(rollouts: pl.DataFrame) -> pl.DataFrame:
    """One row per rollout, status = "active", failed_month = null."""
    return rollouts.with_columns(
        status=pl.lit("active", dtype=pl.Utf8()), failed_month=pl.lit(None, dtype=pl.Int64())
    ).select(list(ROLLOUT_STATUS_SCHEMA.keys()))


def _initial_cash(scenario: Scenario, rollouts: pl.DataFrame) -> pl.DataFrame:
    if not scenario.initial_cash:
        return pl.DataFrame(schema=CASH_BALANCES_SCHEMA)
    entries = pl.DataFrame(
        {
            "agent_id": [e.agent_id for e in scenario.initial_cash],
            "account_id": [e.account_id for e in scenario.initial_cash],
            "balance_usd": [e.balance_usd for e in scenario.initial_cash],
        },
        schema={"agent_id": pl.Utf8(), "account_id": pl.Utf8(), "balance_usd": pl.Float64()},
    )
    return rollouts.join(entries, how="cross").select(list(CASH_BALANCES_SCHEMA.keys()))


def _initial_asset_lots(scenario: Scenario, rollouts: pl.DataFrame) -> pl.DataFrame:
    if not scenario.initial_lots:
        return pl.DataFrame(schema=ASSET_LOT_SCHEMA)
    entries = pl.DataFrame(
        {
            "lot_id": [lot.lot_id for lot in scenario.initial_lots],
            "agent_id": [lot.agent_id for lot in scenario.initial_lots],
            "asset_id": [lot.asset_id for lot in scenario.initial_lots],
            "purchase_month_index": [lot.purchase_month_index for lot in scenario.initial_lots],
            "cost_basis_per_unit_usd": [lot.cost_basis_per_unit_usd for lot in scenario.initial_lots],
            "remaining_quantity": [lot.quantity for lot in scenario.initial_lots],
        },
        schema={
            "lot_id": pl.Utf8(),
            "agent_id": pl.Utf8(),
            "asset_id": pl.Utf8(),
            "purchase_month_index": pl.Int64(),
            "cost_basis_per_unit_usd": pl.Float64(),
            "remaining_quantity": pl.Float64(),
        },
    )
    return rollouts.join(entries, how="cross").select(list(ASSET_LOT_SCHEMA.keys()))


def _initial_ordinary_income_ytd(scenario: Scenario, rollouts: pl.DataFrame) -> pl.DataFrame:
    """One row per (taxed agent, rollout) at YTD = 0. Agents
    without a tax profile aren't tracked here — there's no use
    case for accumulating income on a non-taxed account."""
    if not scenario.tax_profiles:
        return pl.DataFrame(schema=ORDINARY_INCOME_YTD_SCHEMA)
    profile_rows = pl.DataFrame(
        {
            "agent_id": [p.agent_id for p in scenario.tax_profiles],
            "ordinary_income_usd": [0.0] * len(scenario.tax_profiles),
        },
        schema={"agent_id": pl.Utf8(), "ordinary_income_usd": pl.Float64()},
    )
    return rollouts.join(profile_rows, how="cross").select(list(ORDINARY_INCOME_YTD_SCHEMA.keys()))


def _stack_cash_balances(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    """Concatenate per-month cross-sections into the long-form
    state-over-time frame with `month_index` injected."""
    blocks = [
        cs.cash_balances.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(["rollout_index", "month_index", "agent_id", "account_id", "balance_usd"])


def _stack_asset_lots(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    """Concatenate per-month lot cross-sections with `month_index`
    injected. A lot row exists every month from its creation
    onward; `remaining_quantity` shrinks as the lot is sold off."""
    blocks = [
        cs.asset_lots.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(
        [
            "rollout_index",
            "month_index",
            "lot_id",
            "agent_id",
            "asset_id",
            "purchase_month_index",
            "cost_basis_per_unit_usd",
            "remaining_quantity",
        ]
    )


def _stack_income_ytd(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    blocks = [
        cs.ordinary_income_ytd.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(["rollout_index", "month_index", "agent_id", "ordinary_income_usd"])


def _stack_capital_gains(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    blocks = [
        cs.capital_gains_ytd.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(["rollout_index", "month_index", "agent_id", "classification", "gain_usd"])


def _stack_tax_liabilities(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    blocks = [
        cs.tax_liabilities.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(
        ["rollout_index", "month_index", "agent_id", "jurisdiction_id", "tax_year_end_month", "amount_owed_usd"]
    )


def _stack_property_state(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    blocks = [
        cs.property_state.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(
        ["rollout_index", "month_index", "property_id", "location_id", "purchase_month_index", "adjusted_basis_usd"]
    )


def _stack_property_stakes(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    blocks = [
        cs.property_stakes.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(
        [
            "rollout_index",
            "month_index",
            "property_id",
            "agent_id",
            "ownership_pct",
            "contribution_used_usd",
            "equity_ledger_usd",
        ]
    )


def _stack_liabilities(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    blocks = [
        cs.liabilities.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(
        [
            "rollout_index",
            "month_index",
            "liability_id",
            "agent_id",
            "payment_account_id",
            "counterparty_agent_id",
            "counterparty_account_id",
            "property_id",
            "principal_usd",
            "annual_interest_rate",
            "term_months",
            "origination_month_index",
            "monthly_payment_usd",
            "interest_paid_ytd_usd",
            "principal_paid_ytd_usd",
        ]
    )


def _stack_rollout_status(cross_sections: list[StateCrossSection]) -> pl.DataFrame:
    blocks = [
        cs.rollout_status.with_columns(pl.lit(month, dtype=pl.Int64()).alias("month_index"))
        for month, cs in enumerate(cross_sections)
    ]
    return pl.concat(blocks).select(["rollout_index", "month_index", "status", "failed_month"])


def _merge_event_logs(a: EventLog, b: EventLog) -> EventLog:
    """Concatenate two per-phase logs into one per-month log."""
    return EventLog(
        transfers=concat_event_frames([a.transfers, b.transfers], TRANSFER_EVENT_SCHEMA),
        asset_purchases=concat_event_frames([a.asset_purchases, b.asset_purchases], ASSET_PURCHASE_EVENT_SCHEMA),
        lot_dispositions=concat_event_frames([a.lot_dispositions, b.lot_dispositions], LOT_DISPOSITION_EVENT_SCHEMA),
        tax_accruals=concat_event_frames([a.tax_accruals, b.tax_accruals], TAX_ACCRUAL_EVENT_SCHEMA),
        tax_breakdowns=concat_event_frames([a.tax_breakdowns, b.tax_breakdowns], TAX_BREAKDOWN_EVENT_SCHEMA),
        tax_settlements=concat_event_frames([a.tax_settlements, b.tax_settlements], TAX_SETTLEMENT_EVENT_SCHEMA),
        property_purchases=concat_event_frames(
            [a.property_purchases, b.property_purchases], PROPERTY_PURCHASE_EVENT_SCHEMA
        ),
        mortgage_originations=concat_event_frames(
            [a.mortgage_originations, b.mortgage_originations], MORTGAGE_ORIGINATION_EVENT_SCHEMA
        ),
        mortgage_payments=concat_event_frames(
            [a.mortgage_payments, b.mortgage_payments], MORTGAGE_PAYMENT_EVENT_SCHEMA
        ),
        rollout_failures=concat_event_frames([a.rollout_failures, b.rollout_failures], ROLLOUT_FAILURE_EVENT_SCHEMA),
    )


def _concat_events(events_by_month: list[EventLog]) -> EventLog:
    """Concatenate per-month event logs into one cumulative log."""
    return EventLog(
        transfers=concat_event_frames((e.transfers for e in events_by_month), TRANSFER_EVENT_SCHEMA),
        asset_purchases=concat_event_frames((e.asset_purchases for e in events_by_month), ASSET_PURCHASE_EVENT_SCHEMA),
        lot_dispositions=concat_event_frames(
            (e.lot_dispositions for e in events_by_month), LOT_DISPOSITION_EVENT_SCHEMA
        ),
        tax_accruals=concat_event_frames((e.tax_accruals for e in events_by_month), TAX_ACCRUAL_EVENT_SCHEMA),
        tax_breakdowns=concat_event_frames((e.tax_breakdowns for e in events_by_month), TAX_BREAKDOWN_EVENT_SCHEMA),
        tax_settlements=concat_event_frames((e.tax_settlements for e in events_by_month), TAX_SETTLEMENT_EVENT_SCHEMA),
        property_purchases=concat_event_frames(
            (e.property_purchases for e in events_by_month), PROPERTY_PURCHASE_EVENT_SCHEMA
        ),
        mortgage_originations=concat_event_frames(
            (e.mortgage_originations for e in events_by_month), MORTGAGE_ORIGINATION_EVENT_SCHEMA
        ),
        mortgage_payments=concat_event_frames(
            (e.mortgage_payments for e in events_by_month), MORTGAGE_PAYMENT_EVENT_SCHEMA
        ),
        rollout_failures=concat_event_frames(
            (e.rollout_failures for e in events_by_month), ROLLOUT_FAILURE_EVENT_SCHEMA
        ),
    )
