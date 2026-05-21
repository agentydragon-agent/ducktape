"""Product projection composition and simulation service."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import polars as pl

from augur.api.config import Config
from augur.api.scenario_set import ActorRole
from augur.api.schemas import ColumnarTable
from augur.model.exogenous import ExogenousPathModel, ExogenousSamplingRequest
from augur.model.series import INFLATION_SERIES_ID
from augur.product.projection import (
    MetricFanRequest,
    MetricFanResponse,
    MetricName,
    RolloutOutput,
    RolloutRequest,
    RolloutResponse,
    ScenarioKey,
    TerminalMetrics,
)
from augur.sim.external_series import materialize_sampled_exogenous
from augur.sim.run import SimulationRun
from augur.sim.scenario import Agent, InitialAccountBalance, RecurringObligation, Scenario, SeriesIndexedAmount
from augur.sim.simulate import simulate_with_external_series

_PRIMARY_ACCOUNT_ID = "checking"
_SPEND_SINK_AGENT_ID = "spend_sink"
_SPEND_SINK_ACCOUNT_ID = "checking"
_SPEND_OBLIGATION_ID = "monthly_spend"
DEFAULT_CACHE_MAX_ROLLOUTS = 25_000


@dataclass(frozen=True)
class CachedRollout:
    exogenous_model_id: str
    output: RolloutOutput


class ProductProjectionCache:
    def __init__(self, *, max_rollouts: int = DEFAULT_CACHE_MAX_ROLLOUTS) -> None:
        if max_rollouts <= 0:
            raise ValueError("max_rollouts must be positive")
        self._max_rollouts = max_rollouts
        self._rollouts: OrderedDict[tuple[ScenarioKey, int], CachedRollout] = OrderedDict()

    def get(self, scenario: ScenarioKey, seed: int) -> CachedRollout | None:
        key = (scenario, seed)
        cached = self._rollouts.get(key)
        if cached is None:
            return None
        self._rollouts.move_to_end(key)
        return cached

    def put(self, scenario: ScenarioKey, seed: int, rollout: CachedRollout) -> None:
        key = (scenario, seed)
        self._rollouts[key] = rollout
        self._rollouts.move_to_end(key)
        while len(self._rollouts) > self._max_rollouts:
            self._rollouts.popitem(last=False)


class ProductProjectionService:
    def __init__(
        self, *, augur_config: Config, exogenous_model: ExogenousPathModel, cache: ProductProjectionCache | None = None
    ) -> None:
        self._augur_config = augur_config
        self._exogenous_model = exogenous_model
        self._cache = cache or ProductProjectionCache()

    def metric_fan(self, request: MetricFanRequest) -> MetricFanResponse:
        rollouts = self._rollouts_for_seeds(request.scenario, tuple(int(seed) for seed in request.rollout_seeds))
        exogenous_model_id = _exogenous_model_id(rollouts, fallback=request.scenario.exogenous_model_id)
        return MetricFanResponse(
            exogenous_model_id=exogenous_model_id,
            metric=request.metric,
            monthly_metric_fan=_monthly_metric_fan(
                rollouts, metric=request.metric, percentiles=tuple(float(pct) for pct in request.percentiles)
            ),
            terminal_metric_percentiles=_terminal_metric_percentiles(
                rollouts, metric=request.metric, percentiles=tuple(float(pct) for pct in request.percentiles)
            ),
            failed_count=sum(1 for rollout in rollouts if rollout.output.failed),
        )

    def rollout(self, request: RolloutRequest) -> RolloutResponse:
        [rollout] = self._rollouts_for_seeds(request.scenario, (int(request.seed),))
        return RolloutResponse(exogenous_model_id=rollout.exogenous_model_id, rollout=rollout.output)

    def _rollouts_for_seeds(self, scenario: ScenarioKey, seeds: tuple[int, ...]) -> tuple[CachedRollout, ...]:
        if scenario.exogenous_model_id != "current_exogenous_model":
            raise ValueError(f"unsupported exogenous_model_id: {scenario.exogenous_model_id!r}")

        cached_by_seed: dict[int, CachedRollout] = {}
        missing_seeds: list[int] = []
        for seed in seeds:
            cached = self._cache.get(scenario, seed)
            if cached is None:
                missing_seeds.append(seed)
            else:
                cached_by_seed[seed] = cached

        if missing_seeds:
            for seed, rollout in self._simulate_missing_rollouts(scenario, tuple(missing_seeds)):
                cached_by_seed[seed] = rollout
                self._cache.put(scenario, seed, rollout)

        return tuple(cached_by_seed[seed] for seed in seeds)

    def _simulate_missing_rollouts(
        self, scenario_key: ScenarioKey, seeds: tuple[int, ...]
    ) -> tuple[tuple[int, CachedRollout], ...]:
        required_level_series = (
            frozenset({INFLATION_SERIES_ID}) if scenario_key.spend_index == "inflation" else frozenset()
        )
        sampled = self._exogenous_model.sample(
            ExogenousSamplingRequest(
                horizon_months=int(scenario_key.horizon_months),
                rollout_seeds=seeds,
                required_level_series=required_level_series,
            )
        )
        scenario = _scenario_from_key(scenario_key, augur_config=self._augur_config)
        run = simulate_with_external_series(
            scenario, rollout_count=len(seeds), external_series=materialize_sampled_exogenous(sampled)
        )
        initial_cash_usd = float(self._augur_config.snapshot.cash_usd)
        exogenous_model_id = str(sampled.metadata.get("exogenous_model_id") or scenario_key.exogenous_model_id)
        return tuple(
            (
                seed,
                CachedRollout(
                    exogenous_model_id=exogenous_model_id,
                    output=_rollout_output(
                        run, rollout_index=rollout_index, seed=seed, initial_cash_usd=initial_cash_usd
                    ),
                ),
            )
            for rollout_index, seed in enumerate(seeds)
        )


def _scenario_from_key(scenario_key: ScenarioKey, *, augur_config: Config) -> Scenario:
    primary_agent_id = _primary_agent_id(augur_config)
    amount_due_usd: float | SeriesIndexedAmount
    if scenario_key.spend_index == "inflation":
        amount_due_usd = SeriesIndexedAmount(
            base_amount_usd=float(scenario_key.monthly_spend_usd),
            series_id=INFLATION_SERIES_ID,
            adjustment_period_months=1,
        )
    elif scenario_key.spend_index == "none":
        amount_due_usd = float(scenario_key.monthly_spend_usd)
    else:
        raise ValueError(f"unsupported spend_index: {scenario_key.spend_index!r}")

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
                end_month=int(scenario_key.horizon_months) - 1,
                obligation_id=_SPEND_OBLIGATION_ID,
                obligation_type="cash_spend",
                agent_id=primary_agent_id,
                from_account_id=_PRIMARY_ACCOUNT_ID,
                to_agent_id=_SPEND_SINK_AGENT_ID,
                to_account_id=_SPEND_SINK_ACCOUNT_ID,
                amount_due_usd=amount_due_usd,
            )
        ],
        horizon_months=int(scenario_key.horizon_months),
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


def _exogenous_model_id(rollouts: tuple[CachedRollout, ...], *, fallback: str) -> str:
    for rollout in rollouts:
        return rollout.exogenous_model_id
    return fallback


def _monthly_metric_fan(
    rollouts: tuple[CachedRollout, ...], *, metric: MetricName, percentiles: tuple[float, ...]
) -> ColumnarTable:
    rows = []
    for rollout in rollouts:
        columns = rollout.output.monthly_metrics.columns
        month_indices = columns["month_index"]
        metric_values = columns[metric]
        for month_index, value in zip(month_indices, metric_values, strict=True):
            rows.append({"month_index": int(month_index), "value": float(value)})
    if not rows:
        return _columnar(pl.DataFrame([], schema=_metric_fan_schema()))
    frame = pl.DataFrame(rows, schema={"month_index": pl.Int64(), "value": pl.Float64()})
    summaries = []
    for percentile in percentiles:
        quantile = percentile / 100
        summaries.append(
            frame.group_by("month_index")
            .agg(pl.col("value").quantile(quantile, interpolation="linear").alias("value"))
            .with_columns(pl.lit(percentile).alias("percentile"))
            .select("month_index", "percentile", "value")
        )
    return _columnar(pl.concat(summaries).sort("month_index", "percentile"))


def _terminal_metric_percentiles(
    rollouts: tuple[CachedRollout, ...], *, metric: MetricName, percentiles: tuple[float, ...]
) -> ColumnarTable:
    values = [_terminal_metric_value(rollout.output.terminal_metrics, metric) for rollout in rollouts]
    if not values:
        return _columnar(pl.DataFrame([], schema=_terminal_percentiles_schema()))
    frame = pl.DataFrame({"value": values}, schema={"value": pl.Float64()})
    rows = [
        {
            "percentile": percentile,
            "value": frame.select(pl.col("value").quantile(percentile / 100, interpolation="linear")).item(),
        }
        for percentile in percentiles
    ]
    return _columnar(pl.DataFrame(rows, schema=_terminal_percentiles_schema()))


def _terminal_metric_value(terminal: TerminalMetrics, metric: MetricName) -> float:
    match metric:
        case "cash_usd":
            return terminal.cash_usd
        case "net_worth_usd":
            return terminal.net_worth_usd
        case "drawdown_usd":
            return terminal.drawdown_usd
        case "shortfall_usd":
            return terminal.shortfall_usd


def _metric_fan_schema() -> dict[str, pl.DataType]:
    return {"month_index": pl.Int64(), "percentile": pl.Float64(), "value": pl.Float64()}


def _terminal_percentiles_schema() -> dict[str, pl.DataType]:
    return {"percentile": pl.Float64(), "value": pl.Float64()}
