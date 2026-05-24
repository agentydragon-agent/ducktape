"""Decode an R=1 DenseSimulationResult into product-shaped metrics and events."""

from __future__ import annotations

from typing import cast

import numpy as np
import polars as pl

from augur.model.series import home_value_series_id
from augur.product.wire import (
    ClosingCostPaymentEvent,
    MonthlyExpenseEvent,
    MortgagePaymentEvent,
    OutsideRentPaymentEvent,
    PropertyPurchaseEvent,
    PropertyTaxPaymentEvent,
    PublicSecuritySaleEvent,
    RolloutEvent,
    RolloutFailureEvent,
    TaxAccrualEvent,
    TaxPaymentEvent,
    TerminalMetrics,
)
from augur.sim.engine import DenseSimulationResult
from augur.sim.run import SimulationRun
from augur.sim.scenario import ObligationType

_SINGLE_ROLLOUT_INDEX = 0
_TAX_PAYMENT_OBLIGATION_TYPES = (ObligationType.ESTIMATED_TAX, ObligationType.TAX_TRUE_UP)


def monthly_metrics_for_rollout(dense: DenseSimulationResult, *, primary_agent_id: str) -> pl.DataFrame:
    _check_r1(dense)
    plan = dense.plan
    primary_agent_code = _required_string_code(plan.strings, primary_agent_id)
    month_indices = np.arange(plan.horizon_months + 1, dtype=np.int64)
    cash_usd = _cash_by_month(dense, primary_agent_code=primary_agent_code)
    public_security_value_usd = _public_security_value_by_month(dense, primary_agent_code=primary_agent_code)
    property_value_usd = _property_value_by_month(dense, primary_agent_code=primary_agent_code)
    mortgage_balance_usd = _mortgage_balance_by_month(dense, primary_agent_code=primary_agent_code)
    home_equity_usd = property_value_usd - mortgage_balance_usd
    shortfall_usd = _shortfall_by_month(dense, primary_agent_code=primary_agent_code)
    liquid_net_worth_usd = cash_usd + public_security_value_usd
    net_worth_usd = liquid_net_worth_usd + home_equity_usd
    return pl.DataFrame(
        {
            "month_index": month_indices,
            "cash_usd": cash_usd,
            "public_security_value_usd": public_security_value_usd,
            "property_value_usd": property_value_usd,
            "mortgage_balance_usd": mortgage_balance_usd,
            "home_equity_usd": home_equity_usd,
            "liquid_net_worth_usd": liquid_net_worth_usd,
            "net_worth_usd": net_worth_usd,
            "shortfall_usd": shortfall_usd,
        }
    )


def failed_month_index_for_rollout(dense: DenseSimulationResult) -> int | None:
    _check_r1(dense)
    failed_month = int(dense.buffers.rollout_failed_month_state[-1, _SINGLE_ROLLOUT_INDEX])
    return None if failed_month < 0 else failed_month


def terminal_metrics_from(monthly: pl.DataFrame, *, failed_month_index: int | None) -> TerminalMetrics:
    if monthly.is_empty():
        raise ValueError("rollout produced no monthly metrics")
    row = monthly.tail(1).row(0, named=True)
    return TerminalMetrics(
        cash_usd=float(row["cash_usd"]),
        public_security_value_usd=float(row["public_security_value_usd"]),
        property_value_usd=float(row["property_value_usd"]),
        mortgage_balance_usd=float(row["mortgage_balance_usd"]),
        home_equity_usd=float(row["home_equity_usd"]),
        liquid_net_worth_usd=float(row["liquid_net_worth_usd"]),
        net_worth_usd=float(row["net_worth_usd"]),
        shortfall_usd=float(monthly.select(pl.col("shortfall_usd").sum()).item()),
        failed_month_index=failed_month_index,
    )


def rollout_events_from(
    run: SimulationRun, *, primary_agent_id: str, asset_label_by_id: dict[str, str]
) -> tuple[RolloutEvent, ...]:
    events = [
        *_public_security_sale_events(run, primary_agent_id=primary_agent_id, asset_label_by_id=asset_label_by_id),
        *_property_purchase_events(run, primary_agent_id=primary_agent_id),
        *_mortgage_payment_events(run, primary_agent_id=primary_agent_id),
        *_property_tax_payment_events(run, primary_agent_id=primary_agent_id),
        *_tax_accrual_events(run, primary_agent_id=primary_agent_id),
        *_tax_payment_events(run, primary_agent_id=primary_agent_id),
        *_monthly_expense_events(run, primary_agent_id=primary_agent_id),
        *_outside_rent_events(run, primary_agent_id=primary_agent_id),
        *_failure_events(run, primary_agent_id=primary_agent_id),
    ]
    priority = {
        "property_purchase": 0,
        "closing_cost_payment": 1,
        "public_security_sale": 2,
        "tax_accrual": 3,
        "tax_payment": 4,
        "property_tax_payment": 5,
        "mortgage_payment": 6,
        "monthly_expense": 7,
        "outside_rent": 8,
        "failure": 9,
    }
    return tuple(sorted(events, key=lambda event: (event.month_index, priority[event.kind])))


def _check_r1(dense: DenseSimulationResult) -> None:
    if dense.plan.rollout_count != 1:
        raise ValueError(f"decode helpers require rollout_count=1; got {dense.plan.rollout_count}")


def _cash_by_month(dense: DenseSimulationResult, *, primary_agent_code: int) -> np.ndarray:
    cash_slots = np.flatnonzero(dense.plan.cash_agent_codes == primary_agent_code)
    return cast(np.ndarray, dense.buffers.cash_state[:, _SINGLE_ROLLOUT_INDEX, :][:, cash_slots].sum(axis=1))


def _public_security_value_by_month(dense: DenseSimulationResult, *, primary_agent_code: int) -> np.ndarray:
    plan = dense.plan
    values = np.zeros(plan.horizon_months + 1, dtype=np.float64)
    series_index_by_id = {series_id: index for index, series_id in enumerate(plan.series_ids)}
    for lot in range(plan.lot_id_codes.shape[0]):
        if int(plan.lot_agent_codes[lot]) != primary_agent_code:
            continue
        asset_id = plan.strings[int(plan.lot_asset_codes[lot])]
        series_index = series_index_by_id.get(asset_id)
        if series_index is None:
            continue
        price = np.nan_to_num(plan.external_values[series_index, _SINGLE_ROLLOUT_INDEX, :], nan=0.0)
        values += dense.buffers.lot_state[:, _SINGLE_ROLLOUT_INDEX, lot] * price
    return values


def _shortfall_by_month(dense: DenseSimulationResult, *, primary_agent_code: int) -> np.ndarray:
    plan = dense.plan
    shortfall = np.zeros(plan.horizon_months + 1, dtype=np.float64)
    primary_obligations = plan.obligation_agent_codes == primary_agent_code  # [H, O]
    shortfall[1:] = (
        dense.buffers.obligation_shortfall[:, :, _SINGLE_ROLLOUT_INDEX] * primary_obligations.astype(np.float64)
    ).sum(axis=1)
    return shortfall


def _required_string_code(strings: tuple[str, ...], value: str) -> int:
    try:
        return strings.index(value)
    except ValueError as exc:
        raise ValueError(f"compiled simulation string table does not contain {value!r}") from exc


def _public_security_sale_events(
    run: SimulationRun, *, primary_agent_id: str, asset_label_by_id: dict[str, str]
) -> tuple[RolloutEvent, ...]:
    sale_rows = (
        run.events_log.lot_dispositions.filter(pl.col("agent_id") == primary_agent_id)
        .group_by(["month_index", "asset_id"])
        .agg(
            pl.col("units_sold").sum(),
            pl.col("proceeds_usd").sum(),
            pl.col("cost_basis_consumed_usd").sum().alias("cost_basis_usd"),
        )
        .sort("month_index", "asset_id")
    )
    return tuple(
        PublicSecuritySaleEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["proceeds_usd"]),
            asset_id=str(row["asset_id"]),
            asset_label=asset_label_by_id.get(str(row["asset_id"])),
            units=float(row["units_sold"]),
            proceeds_usd=float(row["proceeds_usd"]),
            cost_basis_usd=float(row["cost_basis_usd"]),
        )
        for row in sale_rows.iter_rows(named=True)
    )


def _monthly_expense_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    expense_rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.CASH_SPEND)
    ).sort("month_index", "obligation_id")
    return tuple(
        MonthlyExpenseEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["amount_paid_usd"]),
            amount_due_usd=float(row["amount_due_usd"]),
            amount_paid_usd=float(row["amount_paid_usd"]),
            shortfall_usd=float(row["shortfall_usd"]),
        )
        for row in expense_rows.iter_rows(named=True)
    )


def _outside_rent_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rent_rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.OUTSIDE_RENT)
    ).sort("month_index", "obligation_id")
    return tuple(
        OutsideRentPaymentEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["amount_paid_usd"]),
            amount_due_usd=float(row["amount_due_usd"]),
            amount_paid_usd=float(row["amount_paid_usd"]),
            shortfall_usd=float(row["shortfall_usd"]),
        )
        for row in rent_rows.iter_rows(named=True)
    )


def _tax_accrual_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    keys = ["rollout_index", "month_index", "cause_id", "agent_id", "jurisdiction_id", "tax_year_end_month"]
    breakdown_columns = [
        *keys,
        "ordinary_income_usd",
        "ltcg_usd",
        "stcg_usd",
        "ordinary_tax_usd",
        "capital_gain_tax_usd",
        "total_tax_usd",
    ]
    accrual_rows = (
        run.events_log.tax_accruals.filter(pl.col("agent_id") == primary_agent_id)
        .join(run.events_log.tax_breakdowns.select(breakdown_columns), on=keys, how="left")
        .with_columns(
            ordinary_income_usd=pl.col("ordinary_income_usd").fill_null(0.0),
            ltcg_usd=pl.col("ltcg_usd").fill_null(0.0),
            stcg_usd=pl.col("stcg_usd").fill_null(0.0),
            ordinary_tax_usd=pl.col("ordinary_tax_usd").fill_null(pl.col("amount_usd")),
            capital_gain_tax_usd=pl.col("capital_gain_tax_usd").fill_null(0.0),
            total_tax_usd=pl.col("total_tax_usd").fill_null(pl.col("amount_usd")),
        )
        .sort("month_index", "jurisdiction_id")
    )
    return tuple(
        TaxAccrualEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["amount_usd"]),
            jurisdiction_id=str(row["jurisdiction_id"]),
            tax_year_end_month=int(row["tax_year_end_month"]),
            ordinary_income_usd=float(row["ordinary_income_usd"]),
            ltcg_usd=float(row["ltcg_usd"]),
            stcg_usd=float(row["stcg_usd"]),
            ordinary_tax_usd=float(row["ordinary_tax_usd"]),
            capital_gain_tax_usd=float(row["capital_gain_tax_usd"]),
            total_tax_usd=float(row["total_tax_usd"]),
        )
        for row in accrual_rows.iter_rows(named=True)
    )


def _tax_payment_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    tax_payment_rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & pl.col("obligation_type").is_in(_TAX_PAYMENT_OBLIGATION_TYPES)
    ).sort("month_index", "obligation_id")
    return tuple(
        TaxPaymentEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["amount_paid_usd"]),
            obligation_type=str(row["obligation_type"]),
            amount_due_usd=float(row["amount_due_usd"]),
            amount_paid_usd=float(row["amount_paid_usd"]),
            shortfall_usd=float(row["shortfall_usd"]),
        )
        for row in tax_payment_rows.iter_rows(named=True)
    )


def _failure_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    failure_rows = run.events_log.rollout_failures.filter(pl.col("agent_id") == primary_agent_id)
    return tuple(
        RolloutFailureEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["shortfall_usd"]),
            amount_due_usd=float(row["amount_due_usd"]),
            amount_paid_usd=float(row["amount_paid_usd"]),
            shortfall_usd=float(row["shortfall_usd"]),
        )
        for row in failure_rows.iter_rows(named=True)
    )


def _property_value_by_month(dense: DenseSimulationResult, *, primary_agent_code: int) -> np.ndarray:
    plan = dense.plan
    values = np.zeros(plan.horizon_months + 1, dtype=np.float64)
    series_index_by_id = {series_id: index for index, series_id in enumerate(plan.series_ids)}
    for prop in range(plan.property_id_codes.shape[0]):
        if int(plan.property_buyer_agent_codes[prop]) != primary_agent_code:
            continue
        active = dense.buffers.property_active_state[:, _SINGLE_ROLLOUT_INDEX, prop]
        purchase_month = int(plan.property_month[prop])
        if purchase_month < 0:
            continue
        location_id = plan.strings[int(plan.property_location_codes[prop])]
        series_index = series_index_by_id.get(home_value_series_id(location_id))
        if series_index is None:
            continue
        levels = np.nan_to_num(plan.external_values[series_index, _SINGLE_ROLLOUT_INDEX, :], nan=0.0)
        # State snapshots are H+1 rows: index 0 = pre-month-0 opening, index s = end of month s-1.
        # The property is active starting at snapshot index `purchase_month + 1` (end of purchase month).
        base_level = float(levels[purchase_month])
        if base_level == 0.0:
            continue
        purchase_price = float(plan.property_purchase_price[prop])
        # snapshot s corresponds to month index s-1 for s >= 1; clamp s=0 to month 0 for the base.
        market = purchase_price * levels / base_level
        values += np.where(active, market, 0.0)
    return values


def _mortgage_balance_by_month(dense: DenseSimulationResult, *, primary_agent_code: int) -> np.ndarray:
    plan = dense.plan
    balance = np.zeros(plan.horizon_months + 1, dtype=np.float64)
    for lia in range(plan.liability_codes.shape[0]):
        if int(plan.liability_agent_codes[lia]) != primary_agent_code:
            continue
        balance += dense.buffers.liability_principal_state[:, _SINGLE_ROLLOUT_INDEX, lia]
    return balance


def _property_purchase_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    primary_purchases = run.events_log.property_purchases.filter(pl.col("buyer_agent_id") == primary_agent_id)
    originations = run.events_log.mortgage_originations.select(
        pl.col("rollout_index"),
        pl.col("month_index"),
        pl.col("property_id"),
        pl.col("principal_usd").alias("mortgage_principal_usd"),
    )
    joined = primary_purchases.join(
        originations, on=["rollout_index", "month_index", "property_id"], how="left"
    ).with_columns(mortgage_principal_usd=pl.col("mortgage_principal_usd").fill_null(0.0))
    events: list[RolloutEvent] = []
    for row in joined.iter_rows(named=True):
        events.append(
            PropertyPurchaseEvent(
                month_index=int(row["month_index"]),
                amount_usd=float(row["purchase_price_usd"]),
                property_id=str(row["property_id"]),
                purchase_price_usd=float(row["purchase_price_usd"]),
                # equity_ledger_usd = purchase_price - mortgage_principal (compiler line 866);
                # equals the cash down payment.
                down_payment_usd=float(row["equity_ledger_usd"]),
                mortgage_principal_usd=float(row["mortgage_principal_usd"]),
            )
        )
        closing_cost = float(row["closing_cost_usd"])
        if closing_cost > 0:
            events.append(
                ClosingCostPaymentEvent(
                    month_index=int(row["month_index"]), amount_usd=closing_cost, property_id=str(row["property_id"])
                )
            )
    return tuple(events)


def _mortgage_payment_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    payment_rows = run.events_log.mortgage_payments.filter(pl.col("agent_id") == primary_agent_id).sort("month_index")
    return tuple(
        MortgagePaymentEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["total_payment_usd"]),
            interest_usd=float(row["interest_usd"]),
            principal_usd=float(row["principal_usd"]),
        )
        for row in payment_rows.iter_rows(named=True)
    )


def _property_tax_payment_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.PROPERTY_TAX)
    ).sort("month_index")
    return tuple(
        PropertyTaxPaymentEvent(
            month_index=int(row["month_index"]),
            amount_usd=float(row["amount_paid_usd"]),
            amount_due_usd=float(row["amount_due_usd"]),
            amount_paid_usd=float(row["amount_paid_usd"]),
            shortfall_usd=float(row["shortfall_usd"]),
        )
        for row in rows.iter_rows(named=True)
    )
