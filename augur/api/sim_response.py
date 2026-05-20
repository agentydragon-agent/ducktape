"""Materialize `augur/sim` runs into the existing backend response shape."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import numpy as np
import polars as pl

from augur.core.scenario_set import (
    ReportMetric,
    RolloutStatus,
    RolloutStatusType,
    Scenario,
    ScenarioAcceptedSummary,
    ScenarioResult,
    ScenarioSet,
    ScenarioSetRunResponse,
)
from augur.core.schemas import ColumnarTable
from augur.model.sim_market_series import SP500_SERIES_ID
from augur.sim.run import SimulationRun

MONTHS_PER_YEAR = 12

_LOWER_FAN_PERCENTILES: tuple[int, ...] = (1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45)
_FAN_PERCENTILES: tuple[int, ...] = (
    *_LOWER_FAN_PERCENTILES,
    50,
    *(100 - percentile for percentile in reversed(_LOWER_FAN_PERCENTILES)),
)
_FAN_QUANTILE_LEVELS = np.array(_FAN_PERCENTILES, dtype="float64") / 100.0
_FAN_METRIC_NAMES: tuple[str, ...] = (
    "cash_usd",
    "net_worth_usd",
    "liquid_net_worth_usd",
    "generic_sp500_value_usd",
    "checking_floor_shortfall_usd",
    "property_value_usd",
    "home_equity_usd",
    "owner_home_equity_claim_usd",
    "partner_home_equity_claim_usd",
    "partner_principal_credit_usd",
    "partner_equity_ledger_usd",
    "owner_equity_ledger_usd",
    "partner_ownership_pct",
    "mortgage_balance_usd",
    "rental_income_usd",
    "net_property_cash_flow_usd",
    "property_sale_net_proceeds_usd",
    "net_property_sale_cash_flow_usd",
    "private_equity_value_usd",
    "private_equity_sale_opportunity_value_usd",
)


def scenario_set_response_from_sim_runs(
    *,
    scenario_set: ScenarioSet,
    simulation_runs: Mapping[str, SimulationRun],
    sampled_market_metadata: Mapping[str, object] | None = None,
) -> ScenarioSetRunResponse:
    metadata = dict(sampled_market_metadata or {})
    return ScenarioSetRunResponse(
        scenario_set_id=scenario_set.scenario_set_id,
        request=scenario_set,
        market_request=scenario_set.market_request,
        report_spec=scenario_set.report_spec,
        market_metadata=_market_metadata(
            scenario_set=scenario_set, simulation_runs=simulation_runs, sampled_market_metadata=metadata
        ),
        scenario_results=tuple(
            _scenario_result(
                scenario,
                simulation_runs.get(scenario.scenario_id),
                include_monthly_columns=scenario_set.report_spec.include_monthly_columns,
            )
            for scenario in scenario_set.scenarios
        ),
    )


def _market_metadata(
    *,
    scenario_set: ScenarioSet,
    simulation_runs: Mapping[str, SimulationRun],
    sampled_market_metadata: Mapping[str, object],
) -> dict[str, Any]:
    event_stream_ids = sorted(
        {frame_name for run in simulation_runs.values() for frame_name in _nonempty_event_frame_names(run)}
    )
    return {
        "market_model_id": str(
            sampled_market_metadata.get("market_model_id", scenario_set.market_request.market_model_id)
        ),
        "seed": scenario_set.market_request.seed,
        "rollout_count": scenario_set.market_request.rollout_count,
        "horizon_months": scenario_set.market_request.horizon_months,
        "event_stream_ids": event_stream_ids,
        "source_metadata": dict(sampled_market_metadata),
    }


def _nonempty_event_frame_names(run: SimulationRun) -> set[str]:
    return {
        name
        for name, frame in {
            "transfers": run.events_log.transfers,
            "asset_purchases": run.events_log.asset_purchases,
            "lot_dispositions": run.events_log.lot_dispositions,
            "tax_accruals": run.events_log.tax_accruals,
            "tax_breakdowns": run.events_log.tax_breakdowns,
            "tax_settlements": run.events_log.tax_settlements,
            "obligation_accruals": run.events_log.obligation_accruals,
            "obligation_settlements": run.events_log.obligation_settlements,
            "property_purchases": run.events_log.property_purchases,
            "mortgage_originations": run.events_log.mortgage_originations,
            "mortgage_payments": run.events_log.mortgage_payments,
            "rollout_failures": run.events_log.rollout_failures,
        }.items()
        if not frame.is_empty()
    }


def _scenario_result(scenario: Scenario, run: SimulationRun | None, *, include_monthly_columns: bool) -> ScenarioResult:
    if run is None:
        return ScenarioResult(
            scenario_id=scenario.scenario_id, scenario_label=scenario.label, summary=_accepted_summary(scenario)
        )
    monthly_frame = _monthly_metric_frame(scenario, run)
    monthly_columns = _columnar(monthly_frame)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        scenario_label=scenario.label,
        summary=_accepted_summary(scenario),
        rollout_statuses=_rollout_statuses(run, monthly_frame),
        metric_fan_columns=_metric_fan_columns(monthly_frame),
        monthly_columns=monthly_columns if include_monthly_columns else None,
        terminal_columns=_terminal_columns(monthly_frame),
    )


def _accepted_summary(scenario: Scenario) -> ScenarioAcceptedSummary:
    return ScenarioAcceptedSummary(
        enabled=scenario.enabled, property_id=scenario.property_selection.property_id, location_id=scenario.location_id
    )


def _monthly_metric_frame(scenario: Scenario, run: SimulationRun) -> pl.DataFrame:
    grid = _rollout_month_grid(run)
    cash = _sum_cash(run)
    sp500_value = _sp500_value(run)
    sp500_sales = _sp500_sales(run)
    shortfalls = _shortfalls(run)
    monthly_spend = _monthly_spend(run)
    frame = (
        grid.join(cash, on=["rollout_index", "month_index"], how="left")
        .join(sp500_value, on=["rollout_index", "month_index"], how="left")
        .join(sp500_sales, on=["rollout_index", "month_index"], how="left")
        .join(shortfalls, on=["rollout_index", "month_index"], how="left")
        .join(monthly_spend, on=["rollout_index", "month_index"], how="left")
        .fill_null(0.0)
        .with_columns(
            pl.lit(scenario.scenario_id).alias("scenario_id"),
            pl.lit(scenario.label).alias("scenario_label"),
            generic_sp500_sale_gain_usd=pl.col("generic_sp500_sale_usd") - pl.col("generic_sp500_sale_basis_usd"),
            generic_sp500_sale_tax_usd=pl.lit(0.0),
        )
        .with_columns(
            liquid_net_worth_usd=pl.col("cash_usd") + pl.col("generic_sp500_value_usd"),
            net_worth_usd=pl.col("cash_usd") + pl.col("generic_sp500_value_usd"),
        )
    )
    for metric in ReportMetric:
        if metric is not ReportMetric.MONTH_INDEX and metric.value not in frame.columns:
            frame = frame.with_columns(pl.lit(0.0).alias(metric.value))
    return frame.select(
        "scenario_id",
        "scenario_label",
        pl.col("rollout_index").cast(pl.Int64),
        pl.col("month_index").cast(pl.Int64),
        *(metric.value for metric in ReportMetric if metric is not ReportMetric.MONTH_INDEX),
    )


def _rollout_month_grid(run: SimulationRun) -> pl.DataFrame:
    rollouts = np.array(sorted(run.rollout_status.get_column("rollout_index").to_list()), dtype=np.int64)
    horizon_months = _max_month_index(run)
    return pl.DataFrame(
        {
            "rollout_index": np.repeat(rollouts, horizon_months + 1),
            "month_index": np.tile(np.arange(horizon_months + 1, dtype=np.int64), len(rollouts)),
        },
        schema={"rollout_index": pl.Int64(), "month_index": pl.Int64()},
    )


def _max_month_index(run: SimulationRun) -> int:
    frames = (
        run.cash_balances,
        run.asset_lots,
        run.rollout_status_history,
        run.market_prices,
        run.events_log.lot_dispositions,
        run.events_log.obligation_settlements,
        run.events_log.rollout_failures,
    )
    values = [cast(int, frame.get_column("month_index").max()) for frame in frames if not frame.is_empty()]
    return max(values) if values else 0


def _sum_cash(run: SimulationRun) -> pl.DataFrame:
    if run.cash_balances.is_empty():
        return _empty_metric("cash_usd")
    return run.cash_balances.group_by("rollout_index", "month_index").agg(pl.col("balance_usd").sum().alias("cash_usd"))


def _sp500_value(run: SimulationRun) -> pl.DataFrame:
    lots = run.asset_lots.filter(pl.col("asset_id") == SP500_SERIES_ID)
    if lots.is_empty():
        return _empty_metric("generic_sp500_value_usd")
    return (
        lots.join(run.market_prices, on=["rollout_index", "month_index", "asset_id"], how="left")
        .with_columns(
            (pl.col("remaining_quantity") * pl.col("price_per_unit_usd").fill_null(0.0)).alias(
                "generic_sp500_value_usd"
            )
        )
        .group_by("rollout_index", "month_index")
        .agg(pl.col("generic_sp500_value_usd").sum())
    )


def _sp500_sales(run: SimulationRun) -> pl.DataFrame:
    dispositions = run.events_log.lot_dispositions.filter(pl.col("asset_id") == SP500_SERIES_ID)
    if dispositions.is_empty():
        return _empty_metrics("generic_sp500_sale_usd", "generic_sp500_sale_basis_usd")
    return dispositions.group_by("rollout_index", "month_index").agg(
        pl.col("proceeds_usd").sum().alias("generic_sp500_sale_usd"),
        pl.col("cost_basis_consumed_usd").sum().alias("generic_sp500_sale_basis_usd"),
    )


def _shortfalls(run: SimulationRun) -> pl.DataFrame:
    if run.events_log.rollout_failures.is_empty():
        return _empty_metric("checking_floor_shortfall_usd")
    return run.events_log.rollout_failures.group_by("rollout_index", "month_index").agg(
        pl.col("shortfall_usd").sum().alias("checking_floor_shortfall_usd")
    )


def _monthly_spend(run: SimulationRun) -> pl.DataFrame:
    settlements = run.events_log.obligation_settlements.filter(pl.col("obligation_type") == "monthly_spend")
    if settlements.is_empty():
        return _empty_metric("monthly_spend_usd")
    return settlements.group_by("rollout_index", "month_index").agg(
        pl.col("amount_paid_usd").sum().alias("monthly_spend_usd")
    )


def _empty_metric(name: str) -> pl.DataFrame:
    return _empty_metrics(name)


def _empty_metrics(*names: str) -> pl.DataFrame:
    return pl.DataFrame(
        schema={"rollout_index": pl.Int64(), "month_index": pl.Int64(), **{name: pl.Float64() for name in names}}
    )


def _metric_fan_columns(monthly_frame: pl.DataFrame) -> dict[str, ColumnarTable]:
    return {metric: _fan_columns(monthly_frame, metric) for metric in _FAN_METRIC_NAMES}


def _fan_columns(monthly_frame: pl.DataFrame, metric: str) -> ColumnarTable:
    rollout_count = monthly_frame.get_column("rollout_index").n_unique()
    month_count = monthly_frame.get_column("month_index").n_unique()
    matrix = (
        monthly_frame.sort("rollout_index", "month_index")
        .get_column(metric)
        .to_numpy()
        .astype("float64")
        .reshape(rollout_count, month_count)
    )
    month_index = np.arange(month_count, dtype="int64")
    percentile_values = np.quantile(matrix, _FAN_QUANTILE_LEVELS, axis=0, method="linear")
    columns: dict[str, list[Any]] = {
        "month_index": month_index.tolist(),
        "year": (month_index / MONTHS_PER_YEAR).tolist(),
    }
    for index, percentile in enumerate(_FAN_PERCENTILES):
        columns[f"p{percentile:02d}"] = percentile_values[index].tolist()
    return ColumnarTable(row_count=month_count, columns=columns)


def _terminal_columns(monthly_frame: pl.DataFrame) -> ColumnarTable:
    metric_names = tuple(metric.value for metric in ReportMetric if metric is not ReportMetric.MONTH_INDEX)
    terminal_metric_columns = [f"final_{metric}" for metric in metric_names] + [
        f"total_{metric}" for metric in metric_names
    ]
    terminal = (
        monthly_frame.lazy()
        .group_by("rollout_index", maintain_order=True)
        .agg(
            pl.col("scenario_id").first(),
            pl.col("scenario_label").first(),
            pl.col("month_index").max(),
            *[pl.col(metric).last().alias(f"final_{metric}") for metric in metric_names],
            *[pl.col(metric).sum().alias(f"total_{metric}") for metric in metric_names],
        )
        .sort("rollout_index")
        .with_columns(pl.col("rollout_index").cast(pl.Int64), pl.col("month_index").cast(pl.Int64))
        .select("scenario_id", "scenario_label", "rollout_index", "month_index", *terminal_metric_columns)
        .collect()
    )
    return _columnar(terminal)


def _rollout_statuses(run: SimulationRun, monthly_frame: pl.DataFrame) -> tuple[RolloutStatus, ...]:
    cash_summary = (
        monthly_frame.lazy()
        .group_by("rollout_index", maintain_order=True)
        .agg(
            pl.col("cash_usd").min().alias("min_cash_usd"),
            pl.when(pl.col("cash_usd") < 0).then(pl.col("month_index")).otherwise(None).min().alias("first_negative"),
        )
        .sort("rollout_index")
        .collect()
    )
    failure_by_rollout = _failure_summary_by_rollout(run)
    statuses: list[RolloutStatus] = []
    for row in cash_summary.iter_rows(named=True):
        rollout_index = int(row["rollout_index"])
        min_cash_usd = float(row["min_cash_usd"])
        first_negative = row["first_negative"]
        failure = failure_by_rollout.get(rollout_index)
        status = RolloutStatusType.ACTIVE if first_negative is None else RolloutStatusType.CASH_NEGATIVE
        kwargs: dict[str, Any] = {}
        if first_negative is not None:
            kwargs["first_negative_cash_month_index"] = int(first_negative)
        if failure is not None:
            status = RolloutStatusType.FAILED
            kwargs.update(failure)
        statuses.append(RolloutStatus(rollout_index=rollout_index, status=status, min_cash_usd=min_cash_usd, **kwargs))
    return tuple(statuses)


def _failure_summary_by_rollout(run: SimulationRun) -> dict[int, dict[str, Any]]:
    failures = run.events_log.rollout_failures
    if failures.is_empty():
        return {}
    summary = (
        failures.group_by("rollout_index")
        .agg(
            pl.col("month_index").min().alias("first_failed_obligation_month_index"),
            pl.col("obligation_id").count().alias("failed_obligation_count"),
            pl.col("shortfall_usd").sum().alias("unpaid_obligation_usd"),
        )
        .sort("rollout_index")
    )
    return {
        int(row["rollout_index"]): {
            "first_failed_obligation_month_index": int(row["first_failed_obligation_month_index"]),
            "failed_obligation_count": int(row["failed_obligation_count"]),
            "unpaid_obligation_usd": float(row["unpaid_obligation_usd"]),
        }
        for row in summary.iter_rows(named=True)
    }


def _columnar(frame: pl.DataFrame) -> ColumnarTable:
    return ColumnarTable(row_count=frame.height, columns=frame.to_dict(as_series=False))
