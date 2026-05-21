"""Product projection composition and simulation service."""

from __future__ import annotations

import polars as pl

from augur.api.config import Config
from augur.api.scenario_set import ActorRole
from augur.api.schemas import ColumnarTable
from augur.model.exogenous import ExogenousPathModel, ExogenousSamplingRequest
from augur.model.series import INFLATION_SERIES_ID
from augur.product.projection import ProjectionRequest, ProjectionResponse, RolloutOutput, TerminalMetrics
from augur.sim.external_series import materialize_sampled_exogenous
from augur.sim.run import SimulationRun
from augur.sim.scenario import Agent, InitialAccountBalance, RecurringObligation, Scenario, SeriesIndexedAmount
from augur.sim.simulate import simulate_with_external_series

_PRIMARY_ACCOUNT_ID = "checking"
_SPEND_SINK_AGENT_ID = "spend_sink"
_SPEND_SINK_ACCOUNT_ID = "checking"
_SPEND_OBLIGATION_ID = "monthly_spend"


def run_product_projection(
    request: ProjectionRequest, *, augur_config: Config, exogenous_model: ExogenousPathModel
) -> ProjectionResponse:
    """Run the first narrow product projection through the simulator."""

    if request.exogenous_model_id != "current_exogenous_model":
        raise ValueError(f"unsupported exogenous_model_id: {request.exogenous_model_id!r}")

    required_level_series = frozenset({INFLATION_SERIES_ID}) if request.spend_index == "inflation" else frozenset()
    sampled = exogenous_model.sample(
        ExogenousSamplingRequest(
            horizon_months=int(request.horizon_months),
            rollout_seeds=tuple(int(seed) for seed in request.rollout_seeds),
            required_level_series=required_level_series,
        )
    )
    scenario = _scenario_from_request(request, augur_config=augur_config)
    run = simulate_with_external_series(
        scenario, rollout_count=request.rollout_count, external_series=materialize_sampled_exogenous(sampled)
    )
    initial_cash_usd = float(augur_config.snapshot.cash_usd)
    exogenous_model_id = str(sampled.metadata.get("exogenous_model_id") or request.exogenous_model_id)
    return ProjectionResponse(
        exogenous_model_id=exogenous_model_id,
        horizon_months=int(request.horizon_months),
        rollouts=tuple(
            _rollout_output(run, rollout_index=rollout_index, seed=int(seed), initial_cash_usd=initial_cash_usd)
            for rollout_index, seed in enumerate(request.rollout_seeds)
        ),
    )


def _scenario_from_request(request: ProjectionRequest, *, augur_config: Config) -> Scenario:
    primary_agent_id = _primary_agent_id(augur_config)
    amount_due_usd: float | SeriesIndexedAmount
    if request.spend_index == "inflation":
        amount_due_usd = SeriesIndexedAmount(
            base_amount_usd=float(request.monthly_spend_usd), series_id=INFLATION_SERIES_ID, adjustment_period_months=1
        )
    elif request.spend_index == "none":
        amount_due_usd = float(request.monthly_spend_usd)
    else:
        raise ValueError(f"unsupported spend_index: {request.spend_index!r}")

    return Scenario(
        agents=[Agent(agent_id=primary_agent_id), Agent(agent_id=_SPEND_SINK_AGENT_ID)],
        initial_cash=[
            InitialAccountBalance(
                agent_id=primary_agent_id,
                account_id=_PRIMARY_ACCOUNT_ID,
                balance_usd=float(augur_config.snapshot.cash_usd),
            ),
            InitialAccountBalance(agent_id=_SPEND_SINK_AGENT_ID, account_id=_SPEND_SINK_ACCOUNT_ID, balance_usd=0.0),
        ],
        recurring_obligations=[
            RecurringObligation(
                start_month=0,
                end_month=int(request.horizon_months) - 1,
                obligation_id=_SPEND_OBLIGATION_ID,
                obligation_type="cash_spend",
                agent_id=primary_agent_id,
                from_account_id=_PRIMARY_ACCOUNT_ID,
                to_agent_id=_SPEND_SINK_AGENT_ID,
                to_account_id=_SPEND_SINK_ACCOUNT_ID,
                amount_due_usd=amount_due_usd,
            )
        ],
        horizon_months=int(request.horizon_months),
    )


def _primary_agent_id(augur_config: Config) -> str:
    primary_agents = [agent.actor_id for agent in augur_config.agents if agent.role == ActorRole.PRIMARY_OWNER]
    if len(primary_agents) != 1:
        raise ValueError(f"expected exactly one primary owner agent; got {primary_agents}")
    return primary_agents[0]


def _rollout_output(run: SimulationRun, *, rollout_index: int, seed: int, initial_cash_usd: float) -> RolloutOutput:
    monthly = _monthly_metrics(run, rollout_index=rollout_index, initial_cash_usd=initial_cash_usd)
    terminal = _terminal_metrics(run, monthly, rollout_index=rollout_index)
    return RolloutOutput(
        seed=seed,
        failed=terminal.failed_month_index is not None,
        monthly_metrics=_columnar(monthly),
        terminal_metrics=terminal,
    )


def _monthly_metrics(run: SimulationRun, *, rollout_index: int, initial_cash_usd: float) -> pl.DataFrame:
    cash = (
        run.cash_balances.filter(
            (pl.col("rollout_index") == rollout_index)
            & (pl.col("agent_id") != _SPEND_SINK_AGENT_ID)
            & (pl.col("account_id") == _PRIMARY_ACCOUNT_ID)
        )
        .group_by("month_index")
        .agg(pl.col("balance_usd").sum().alias("cash_usd"))
        .sort("month_index")
    )
    shortfall = _monthly_shortfalls(run, rollout_index=rollout_index)
    return (
        cash.join(shortfall, on="month_index", how="left")
        .with_columns(
            pl.col("shortfall_usd").fill_null(0.0),
            pl.col("cash_usd").alias("net_worth_usd"),
            pl.max_horizontal(0.0, pl.lit(initial_cash_usd, dtype=pl.Float64()) - pl.col("cash_usd")).alias(
                "drawdown_usd"
            ),
        )
        .select("month_index", "cash_usd", "net_worth_usd", "drawdown_usd", "shortfall_usd")
    )


def _monthly_shortfalls(run: SimulationRun, *, rollout_index: int) -> pl.DataFrame:
    settlements = run.events_log.obligation_settlements
    if settlements.is_empty():
        return pl.DataFrame(
            {"month_index": [], "shortfall_usd": []}, schema={"month_index": pl.Int64(), "shortfall_usd": pl.Float64()}
        )
    return (
        settlements.filter((pl.col("rollout_index") == rollout_index) & (pl.col("shortfall_usd") > 0))
        .with_columns((pl.col("month_index") + 1).alias("month_index"))
        .group_by("month_index")
        .agg(pl.col("shortfall_usd").sum())
        .sort("month_index")
    )


def _terminal_metrics(run: SimulationRun, monthly: pl.DataFrame, *, rollout_index: int) -> TerminalMetrics:
    if monthly.is_empty():
        raise ValueError(f"rollout {rollout_index} produced no monthly metrics")
    row = monthly.tail(1).row(0, named=True)
    failed_month_index = _failed_month_index(run, rollout_index=rollout_index)
    return TerminalMetrics(
        cash_usd=float(row["cash_usd"]),
        net_worth_usd=float(row["net_worth_usd"]),
        drawdown_usd=float(row["drawdown_usd"]),
        shortfall_usd=_total_shortfall(monthly),
        failed_month_index=failed_month_index,
    )


def _failed_month_index(run: SimulationRun, *, rollout_index: int) -> int | None:
    status = run.rollout_status.filter(pl.col("rollout_index") == rollout_index)
    if status.is_empty():
        raise ValueError(f"missing rollout status for rollout {rollout_index}")
    failed_month = status.row(0, named=True)["failed_month"]
    return None if failed_month is None else int(failed_month)


def _total_shortfall(monthly: pl.DataFrame) -> float:
    return float(monthly.select(pl.col("shortfall_usd").sum()).item())


def _columnar(frame: pl.DataFrame) -> ColumnarTable:
    return ColumnarTable(row_count=frame.height, columns=frame.to_dict(as_series=False))
