"""Materialize `augur/sim` runs into the existing backend response shape."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import numpy as np
import polars as pl

from augur.api.scenario_set import (
    ActorRole,
    ExogenousPathIdentity,
    ProjectionRun,
    ProjectionTrajectoryIdentity,
    ReportMetric,
    RolloutStatus,
    RolloutStatusType,
    Scenario,
    ScenarioAcceptedSummary,
    ScenarioResult,
    ScenarioSet,
    ScenarioSetRunResponse,
)
from augur.api.schemas import Frame
from augur.model.provenance import stable_identity_digest
from augur.model.series import PRIVATE_EQUITY_SERIES_PREFIX, SP500_SERIES_ID
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


def scenario_set_response_from_runs(
    *,
    scenario_set: ScenarioSet,
    simulation_runs: Mapping[str, SimulationRun],
    sampled_exogenous_metadata: Mapping[str, object] | None = None,
) -> ScenarioSetRunResponse:
    metadata = dict(sampled_exogenous_metadata or {})
    event_stream_ids = _exogenous_event_stream_ids(metadata)
    path_set_id = _path_set_id(
        scenario_set=scenario_set,
        simulation_runs=simulation_runs,
        sampled_exogenous_metadata=metadata,
        event_stream_ids=event_stream_ids,
    )
    exogenous_paths = _exogenous_paths(
        scenario_set=scenario_set,
        path_set_id=path_set_id,
        sampled_exogenous_metadata=metadata,
        event_stream_ids=event_stream_ids,
    )
    exogenous_path_by_rollout = {path.rollout_index: path for path in exogenous_paths}
    scenario_input_ids = {scenario.scenario_id: _scenario_input_id(scenario) for scenario in scenario_set.scenarios}
    return ScenarioSetRunResponse(
        scenario_set_id=scenario_set.scenario_set_id,
        request=scenario_set,
        sampling_request=scenario_set.sampling_request,
        report_spec=scenario_set.report_spec,
        projection_run=ProjectionRun(
            projection_run_id=_projection_run_id(
                scenario_set_id=scenario_set.scenario_set_id,
                path_set_id=path_set_id,
                scenario_input_ids=tuple(scenario_input_ids.values()),
            ),
            scenario_set_id=scenario_set.scenario_set_id,
            path_set_id=path_set_id,
            scenario_input_ids=tuple(scenario_input_ids.values()),
        ),
        exogenous_paths=exogenous_paths,
        sampling_metadata=_sampling_metadata(
            scenario_set=scenario_set, simulation_runs=simulation_runs, sampled_exogenous_metadata=metadata
        ),
        scenario_results=tuple(
            _scenario_result(
                scenario,
                simulation_runs.get(scenario.scenario_id),
                include_monthly_columns=scenario_set.report_spec.include_monthly_columns,
                path_set_id=path_set_id,
                scenario_input_id=scenario_input_ids[scenario.scenario_id],
                exogenous_path_by_rollout=exogenous_path_by_rollout,
            )
            for scenario in scenario_set.scenarios
        ),
    )


def _sampling_metadata(
    *,
    scenario_set: ScenarioSet,
    simulation_runs: Mapping[str, SimulationRun],
    sampled_exogenous_metadata: Mapping[str, object],
) -> dict[str, Any]:
    event_stream_ids = sorted(
        {frame_name for run in simulation_runs.values() for frame_name in _nonempty_event_frame_names(run)}
    )
    return {
        "exogenous_model_id": str(
            sampled_exogenous_metadata.get("exogenous_model_id", scenario_set.sampling_request.exogenous_model_id)
        ),
        "seed": scenario_set.sampling_request.seed,
        "rollout_count": scenario_set.sampling_request.rollout_count,
        "horizon_months": scenario_set.sampling_request.horizon_months,
        "event_stream_ids": event_stream_ids,
    }


def _path_set_id(
    *,
    scenario_set: ScenarioSet,
    simulation_runs: Mapping[str, SimulationRun],
    sampled_exogenous_metadata: Mapping[str, object],
    event_stream_ids: tuple[str, ...],
) -> str:
    return "path_set:" + stable_identity_digest(
        {
            "sampling_request": scenario_set.sampling_request,
            "sampling_metadata": sampled_exogenous_metadata,
            "level_series_ids": _level_series_ids(simulation_runs),
            "event_stream_ids": event_stream_ids,
        }
    )


def _scenario_input_id(scenario: Scenario) -> str:
    return "scenario_input:" + stable_identity_digest({"scenario": scenario})


def _policy_program_set_id(scenario: Scenario) -> str:
    return "policy_program_set:" + stable_identity_digest(
        {"scenario_id": scenario.scenario_id, "policies": scenario.policies}
    )


def _projection_run_id(*, scenario_set_id: str, path_set_id: str, scenario_input_ids: tuple[str, ...]) -> str:
    return "projection_run:" + stable_identity_digest(
        {"scenario_set_id": scenario_set_id, "path_set_id": path_set_id, "scenario_input_ids": scenario_input_ids}
    )


def _projection_trajectory_id(
    *, scenario_id: str, rollout_index: int, path_set_id: str, scenario_input_id: str, policy_program_set_id: str
) -> str:
    return "projection_trajectory:" + stable_identity_digest(
        {
            "scenario_id": scenario_id,
            "rollout_index": rollout_index,
            "path_set_id": path_set_id,
            "scenario_input_id": scenario_input_id,
            "policy_program_set_id": policy_program_set_id,
        }
    )


def _level_series_ids(simulation_runs: Mapping[str, SimulationRun]) -> tuple[str, ...]:
    series_ids: set[str] = set()
    for run in simulation_runs.values():
        if run.series_values.is_empty():
            continue
        series_ids.update(str(series_id) for series_id in run.series_values.get_column("series_id").unique().to_list())
    return tuple(sorted(series_ids))


def _exogenous_event_stream_ids(sampled_exogenous_metadata: Mapping[str, object]) -> tuple[str, ...]:
    raw_ids = sampled_exogenous_metadata.get("event_stream_ids", ())
    if raw_ids is None:
        return ()
    if isinstance(raw_ids, str):
        return (raw_ids,)
    if not isinstance(raw_ids, tuple | list | set | frozenset):
        return (str(raw_ids),)
    return tuple(sorted(str(stream_id) for stream_id in raw_ids))


def _exogenous_paths(
    *,
    scenario_set: ScenarioSet,
    path_set_id: str,
    sampled_exogenous_metadata: Mapping[str, object],
    event_stream_ids: tuple[str, ...],
) -> tuple[ExogenousPathIdentity, ...]:
    rollout_seeds = _rollout_seeds(scenario_set)
    return tuple(
        ExogenousPathIdentity(
            rollout_index=rollout_index,
            path_set_id=path_set_id,
            exogenous_path_id=f"{path_set_id}:rollout:{rollout_index}",
            exogenous_model_id=str(
                sampled_exogenous_metadata.get("exogenous_model_id", scenario_set.sampling_request.exogenous_model_id)
            ),
            exogenous_model_version_id=str(
                sampled_exogenous_metadata.get(
                    "exogenous_model_version_id", sampled_exogenous_metadata.get("model_version_id", "unknown")
                )
            ),
            scenario_generator_id=str(
                sampled_exogenous_metadata.get("scenario_generator_id", "exogenous_model_provider")
            ),
            scenario_generator_version_id=str(
                sampled_exogenous_metadata.get("scenario_generator_version_id", "unknown")
            ),
            evidence_set_id=str(sampled_exogenous_metadata.get("evidence_set_id", "unknown")),
            calibration_artifact_id=str(sampled_exogenous_metadata.get("calibration_artifact_id", "unknown")),
            seed=seed,
            event_stream_ids=event_stream_ids,
        )
        for rollout_index, seed in enumerate(rollout_seeds)
    )


def _rollout_seeds(scenario_set: ScenarioSet) -> tuple[int, ...]:
    return tuple(
        int(child.generate_state(1, dtype=np.uint32)[0])
        for child in np.random.SeedSequence(scenario_set.sampling_request.seed).spawn(
            scenario_set.sampling_request.rollout_count
        )
    )


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


def _scenario_result(
    scenario: Scenario,
    run: SimulationRun | None,
    *,
    include_monthly_columns: bool,
    path_set_id: str,
    scenario_input_id: str,
    exogenous_path_by_rollout: Mapping[int, ExogenousPathIdentity],
) -> ScenarioResult:
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
        projection_trajectories=_projection_trajectories(
            scenario=scenario,
            run=run,
            path_set_id=path_set_id,
            scenario_input_id=scenario_input_id,
            exogenous_path_by_rollout=exogenous_path_by_rollout,
        ),
        rollout_statuses=_rollout_statuses(run, monthly_frame),
        metric_fan_columns=_metric_fan_columns(monthly_frame),
        monthly_columns=monthly_columns if include_monthly_columns else None,
        terminal_columns=_terminal_columns(monthly_frame),
    )


def _projection_trajectories(
    *,
    scenario: Scenario,
    run: SimulationRun,
    path_set_id: str,
    scenario_input_id: str,
    exogenous_path_by_rollout: Mapping[int, ExogenousPathIdentity],
) -> tuple[ProjectionTrajectoryIdentity, ...]:
    policy_program_set_id = _policy_program_set_id(scenario)
    rollout_indices = sorted(int(rollout_index) for rollout_index in run.rollout_status.get_column("rollout_index"))
    return tuple(
        ProjectionTrajectoryIdentity(
            scenario_id=scenario.scenario_id,
            rollout_index=rollout_index,
            path_set_id=path_set_id,
            exogenous_path_id=exogenous_path_by_rollout[rollout_index].exogenous_path_id,
            scenario_input_id=scenario_input_id,
            policy_program_set_id=policy_program_set_id,
            projection_trajectory_id=_projection_trajectory_id(
                scenario_id=scenario.scenario_id,
                rollout_index=rollout_index,
                path_set_id=path_set_id,
                scenario_input_id=scenario_input_id,
                policy_program_set_id=policy_program_set_id,
            ),
        )
        for rollout_index in rollout_indices
    )


def _accepted_summary(scenario: Scenario) -> ScenarioAcceptedSummary:
    return ScenarioAcceptedSummary(
        enabled=scenario.enabled,
        property_id=scenario.property_selection.property_id,
        location_id=scenario.property_selection.location_id,
    )


def _monthly_metric_frame(scenario: Scenario, run: SimulationRun) -> pl.DataFrame:
    report_agent_id = _report_agent_id(scenario)
    grid = _rollout_month_grid(run)
    cash = _sum_cash(run, agent_id=report_agent_id)
    sp500_value = _sp500_value(run, agent_id=report_agent_id)
    private_equity_value = _private_equity_value(run, agent_id=report_agent_id)
    sp500_sales = _sp500_sales(run, agent_id=report_agent_id)
    shortfalls = _shortfalls(run, agent_id=report_agent_id)
    monthly_spend = _monthly_spend(run, agent_id=report_agent_id)
    property_position = _property_position(run, agent_id=report_agent_id)
    mortgage_payments = _mortgage_payments(run, agent_id=report_agent_id)
    purchase_closing_costs = _purchase_closing_costs(run, agent_id=report_agent_id)
    property_carrying_costs = _property_carrying_costs(run, agent_id=report_agent_id)
    frame = (
        grid.join(cash, on=["rollout_index", "month_index"], how="left")
        .join(sp500_value, on=["rollout_index", "month_index"], how="left")
        .join(private_equity_value, on=["rollout_index", "month_index"], how="left")
        .join(sp500_sales, on=["rollout_index", "month_index"], how="left")
        .join(shortfalls, on=["rollout_index", "month_index"], how="left")
        .join(monthly_spend, on=["rollout_index", "month_index"], how="left")
        .join(property_position, on=["rollout_index", "month_index"], how="left")
        .join(mortgage_payments, on=["rollout_index", "month_index"], how="left")
        .join(purchase_closing_costs, on=["rollout_index", "month_index"], how="left")
        .join(property_carrying_costs, on=["rollout_index", "month_index"], how="left")
        .fill_null(0.0)
        .with_columns(
            pl.lit(scenario.scenario_id).alias("scenario_id"),
            pl.lit(scenario.label).alias("scenario_label"),
            generic_sp500_sale_gain_usd=pl.col("generic_sp500_sale_usd") - pl.col("generic_sp500_sale_basis_usd"),
            generic_sp500_sale_tax_usd=pl.lit(0.0),
            property_carrying_cost_usd=pl.sum_horizontal(
                "property_tax_usd", "hoa_usd", "insurance_usd", "maintenance_usd"
            ),
        )
        .with_columns(
            liquid_net_worth_usd=pl.col("cash_usd") + pl.col("generic_sp500_value_usd"),
            net_worth_usd=pl.col("cash_usd")
            + pl.col("generic_sp500_value_usd")
            + pl.col("private_equity_value_usd")
            + pl.col("property_value_usd")
            - pl.col("mortgage_balance_usd"),
        )
    )
    for metric in ReportMetric:
        if metric is not ReportMetric.MONTH_INDEX and metric not in frame.columns:
            frame = frame.with_columns(pl.lit(0.0).alias(metric))
    frame = frame.with_columns(
        net_property_cash_flow_usd=pl.col("rental_income_usd")
        - pl.col("rental_management_fee_usd")
        - pl.col("rental_leasing_fee_usd")
        - pl.col("property_carrying_cost_usd")
        - pl.col("mortgage_payment_usd")
    )
    return frame.select(
        "scenario_id",
        "scenario_label",
        pl.col("rollout_index").cast(pl.Int64),
        pl.col("month_index").cast(pl.Int64),
        *(metric for metric in ReportMetric if metric is not ReportMetric.MONTH_INDEX),
    )


def _report_agent_id(scenario: Scenario) -> str:
    primary_owner_ids = [actor.actor_id for actor in scenario.actors if actor.role is ActorRole.PRIMARY_OWNER]
    if len(primary_owner_ids) == 1:
        return primary_owner_ids[0]
    return scenario.actors[0].actor_id


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
        run.property_state,
        run.property_stakes,
        run.liabilities,
        run.rollout_status_history,
        run.series_values,
        run.events_log.lot_dispositions,
        run.events_log.property_purchases,
        run.events_log.mortgage_payments,
        run.events_log.obligation_settlements,
        run.events_log.rollout_failures,
    )
    values = [cast(int, frame.get_column("month_index").max()) for frame in frames if not frame.is_empty()]
    return max(values) if values else 0


def _sum_cash(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    if run.cash_balances.is_empty():
        return _empty_metric("cash_usd")
    return (
        run.cash_balances.filter(pl.col("agent_id") == agent_id)
        .group_by("rollout_index", "month_index")
        .agg(pl.col("balance_usd").sum().alias("cash_usd"))
    )


def _sp500_value(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    lots = run.asset_lots.filter((pl.col("agent_id") == agent_id) & (pl.col("asset_id") == SP500_SERIES_ID))
    if lots.is_empty():
        return _empty_metric("generic_sp500_value_usd")
    return (
        lots.join(
            run.series_values,
            left_on=["rollout_index", "month_index", "asset_id"],
            right_on=["rollout_index", "month_index", "series_id"],
            how="left",
        )
        .with_columns((pl.col("remaining_quantity") * pl.col("value").fill_null(0.0)).alias("generic_sp500_value_usd"))
        .group_by("rollout_index", "month_index")
        .agg(pl.col("generic_sp500_value_usd").sum())
    )


def _private_equity_value(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    lots = run.asset_lots.filter(
        (pl.col("agent_id") == agent_id) & pl.col("asset_id").str.starts_with(PRIVATE_EQUITY_SERIES_PREFIX)
    )
    if lots.is_empty():
        return _empty_metric("private_equity_value_usd")
    return (
        lots.join(
            run.series_values,
            left_on=["rollout_index", "month_index", "asset_id"],
            right_on=["rollout_index", "month_index", "series_id"],
            how="left",
        )
        .with_columns((pl.col("remaining_quantity") * pl.col("value").fill_null(0.0)).alias("private_equity_value_usd"))
        .group_by("rollout_index", "month_index")
        .agg(pl.col("private_equity_value_usd").sum())
    )


def _sp500_sales(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    dispositions = run.events_log.lot_dispositions.filter(
        (pl.col("agent_id") == agent_id) & (pl.col("asset_id") == SP500_SERIES_ID)
    )
    if dispositions.is_empty():
        return _empty_metrics("generic_sp500_sale_usd", "generic_sp500_sale_basis_usd")
    return dispositions.group_by("rollout_index", "month_index").agg(
        pl.col("proceeds_usd").sum().alias("generic_sp500_sale_usd"),
        pl.col("cost_basis_consumed_usd").sum().alias("generic_sp500_sale_basis_usd"),
    )


def _shortfalls(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    if run.events_log.rollout_failures.is_empty():
        return _empty_metric("checking_floor_shortfall_usd")
    return (
        run.events_log.rollout_failures.filter(pl.col("agent_id") == agent_id)
        .group_by("rollout_index", "month_index")
        .agg(pl.col("shortfall_usd").sum().alias("checking_floor_shortfall_usd"))
    )


def _monthly_spend(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    settlements = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == agent_id) & (pl.col("obligation_type") == "monthly_spend")
    )
    if settlements.is_empty():
        return _empty_metric("monthly_spend_usd")
    return settlements.group_by("rollout_index", "month_index").agg(
        pl.col("amount_paid_usd").sum().alias("monthly_spend_usd")
    )


def _property_position(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    if run.property_state.is_empty() or run.property_stakes.is_empty():
        return _empty_metrics(
            "property_value_usd",
            "mortgage_balance_usd",
            "home_equity_usd",
            "owner_home_equity_claim_usd",
            "owner_equity_ledger_usd",
        )
    property_value = (
        run.property_stakes.filter(pl.col("agent_id") == agent_id)
        .join(run.property_state, on=["rollout_index", "month_index", "property_id"], how="inner")
        .join(
            run.events_log.property_purchases.select(
                "rollout_index",
                "property_id",
                pl.col("month_index").alias("purchase_month_index"),
                "purchase_price_usd",
            ),
            on=["rollout_index", "property_id", "purchase_month_index"],
            how="left",
        )
        .group_by("rollout_index", "month_index")
        .agg(
            (pl.col("purchase_price_usd").fill_null(pl.col("adjusted_basis_usd")) * pl.col("ownership_pct"))
            .sum()
            .alias("property_value_usd"),
            pl.col("equity_ledger_usd").sum().alias("owner_equity_ledger_usd"),
        )
    )
    if run.liabilities.is_empty():
        mortgage_balance = _empty_metric("mortgage_balance_usd")
    else:
        mortgage_balance = (
            run.liabilities.filter(pl.col("agent_id") == agent_id)
            .group_by("rollout_index", "month_index")
            .agg(pl.col("principal_usd").sum().alias("mortgage_balance_usd"))
        )
    return (
        property_value.join(mortgage_balance, on=["rollout_index", "month_index"], how="left")
        .with_columns(pl.col("mortgage_balance_usd").fill_null(0.0))
        .with_columns(
            home_equity_usd=pl.col("property_value_usd") - pl.col("mortgage_balance_usd"),
            owner_home_equity_claim_usd=pl.col("property_value_usd") - pl.col("mortgage_balance_usd"),
        )
    )


def _mortgage_payments(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    payments = run.events_log.mortgage_payments.filter(pl.col("agent_id") == agent_id)
    if payments.is_empty():
        return _empty_metrics("mortgage_interest_usd", "mortgage_principal_usd", "mortgage_payment_usd")
    return payments.group_by("rollout_index", "month_index").agg(
        pl.col("interest_usd").sum().alias("mortgage_interest_usd"),
        pl.col("principal_usd").sum().alias("mortgage_principal_usd"),
        pl.col("total_payment_usd").sum().alias("mortgage_payment_usd"),
    )


def _purchase_closing_costs(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    purchases = run.events_log.property_purchases.filter(pl.col("buyer_agent_id") == agent_id)
    if purchases.is_empty():
        return _empty_metric("purchase_closing_cost_usd")
    return purchases.group_by("rollout_index", "month_index").agg(
        pl.col("closing_cost_usd").sum().alias("purchase_closing_cost_usd")
    )


def _property_carrying_costs(run: SimulationRun, *, agent_id: str) -> pl.DataFrame:
    settlements = run.events_log.obligation_settlements.filter(pl.col("agent_id") == agent_id)
    if settlements.is_empty():
        return _empty_metrics("property_tax_usd", "hoa_usd", "insurance_usd", "maintenance_usd")
    metrics = (
        settlements.with_columns(
            _metric=pl.col("obligation_type").replace_strict(
                {
                    "property_tax": "property_tax_usd",
                    "hoa_dues": "hoa_usd",
                    "insurance_premium": "insurance_usd",
                    "maintenance": "maintenance_usd",
                    "special_assessment": "hoa_usd",
                },
                default=None,
            )
        )
        .filter(pl.col("_metric").is_not_null())
        .group_by("rollout_index", "month_index", "_metric")
        .agg(pl.col("amount_paid_usd").sum())
        .pivot(index=["rollout_index", "month_index"], on="_metric", values="amount_paid_usd")
    )
    for name in ("property_tax_usd", "hoa_usd", "insurance_usd", "maintenance_usd"):
        if name not in metrics.columns:
            metrics = metrics.with_columns(pl.lit(0.0).alias(name))
    return metrics.select(
        "rollout_index", "month_index", "property_tax_usd", "hoa_usd", "insurance_usd", "maintenance_usd"
    )


def _empty_metric(name: str) -> pl.DataFrame:
    return _empty_metrics(name)


def _empty_metrics(*names: str) -> pl.DataFrame:
    return pl.DataFrame(
        schema={"rollout_index": pl.Int64(), "month_index": pl.Int64(), **{name: pl.Float64() for name in names}}
    )


def _metric_fan_columns(monthly_frame: pl.DataFrame) -> dict[str, Frame]:
    return {metric: _fan_columns(monthly_frame, metric) for metric in _FAN_METRIC_NAMES}


def _fan_columns(monthly_frame: pl.DataFrame, metric: str) -> Frame:
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
    columns: Frame = {"month_index": month_index.tolist(), "year": (month_index / MONTHS_PER_YEAR).tolist()}
    for index, percentile in enumerate(_FAN_PERCENTILES):
        columns[f"p{percentile:02d}"] = percentile_values[index].tolist()
    return columns


def _terminal_columns(monthly_frame: pl.DataFrame) -> Frame:
    metric_names = tuple(metric for metric in ReportMetric if metric is not ReportMetric.MONTH_INDEX)
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


def _columnar(frame: pl.DataFrame) -> Frame:
    return frame.to_dict(as_series=False)
