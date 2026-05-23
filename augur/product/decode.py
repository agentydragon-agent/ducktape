"""Decode an R=1 DenseSimulationResult into product-shaped metrics and events."""

from __future__ import annotations

from typing import cast

import numpy as np
import polars as pl

from augur.product.wire import (
    MonthlyExpenseEvent,
    PublicSecuritySaleEvent,
    RolloutEvent,
    RolloutFailureEvent,
    TaxAccrualEvent,
    TaxPaymentEvent,
    TerminalMetrics,
)
from augur.sim.engine import DenseSimulationResult
from augur.sim.run import SimulationRun

_SINGLE_ROLLOUT_INDEX = 0


def monthly_metrics_for_rollout(dense: DenseSimulationResult, *, primary_agent_id: str) -> pl.DataFrame:
    _check_r1(dense)
    plan = dense.plan
    primary_agent_code = _required_string_code(plan.strings, primary_agent_id)
    month_indices = np.arange(plan.horizon_months + 1, dtype=np.int64)
    cash_usd = _cash_by_month(dense, primary_agent_code=primary_agent_code)
    public_security_value_usd = _public_security_value_by_month(dense, primary_agent_code=primary_agent_code)
    shortfall_usd = _shortfall_by_month(dense, primary_agent_code=primary_agent_code)
    liquid_net_worth_usd = cash_usd + public_security_value_usd
    net_worth_usd = liquid_net_worth_usd
    return pl.DataFrame(
        {
            "month_index": month_indices,
            "cash_usd": cash_usd,
            "public_security_value_usd": public_security_value_usd,
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
        *_tax_accrual_events(run, primary_agent_id=primary_agent_id),
        *_tax_payment_events(run, primary_agent_id=primary_agent_id),
        *_monthly_expense_events(run, primary_agent_id=primary_agent_id),
        *_failure_events(run, primary_agent_id=primary_agent_id),
    ]
    priority = {"public_security_sale": 0, "tax_accrual": 1, "tax_payment": 2, "monthly_expense": 3, "failure": 4}
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
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == "cash_spend")
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
        (pl.col("agent_id") == primary_agent_id) & pl.col("obligation_type").is_in(["estimated_tax", "tax_true_up"])
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
