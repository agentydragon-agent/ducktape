"""Product-shaped query surface. Owns the rollout LRU cache and the exogenous model.

Holds the slice of augur config the product surface needs (portfolio, primary
agent, initial cash); does not know about properties, locations, or bootstrap.
The cache stores per-rollout R=1 DenseSimulationResult primitives keyed by
``(ScenarioKey, seed)``.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import cast

import numpy as np
import polars as pl

from augur.api.bootstrap import Property
from augur.api.portfolio import PortfolioConfig
from augur.api.schemas import Frame
from augur.model.exogenous import ExogenousSamplingRequest, Sampler, anchor_sampled_series_levels
from augur.product.decode import (
    failed_month_index_for_rollout,
    monthly_metrics_for_rollout,
    rollout_events_from,
    terminal_metrics_from,
)
from augur.product.scenarios import (
    asset_label_by_series_id,
    build_scenario,
    initial_lots_from_portfolio,
    required_level_series,
)
from augur.product.wire import (
    MetricFanRequest,
    MetricFanResponse,
    MetricName,
    RolloutOutput,
    RolloutRequest,
    RolloutResponse,
    RolloutSummary,
    ScenarioKey,
    TerminalMetrics,
)
from augur.sim.engine import DenseSimulationResult
from augur.sim.external_series import materialize_sampled_exogenous
from augur.sim.simulate import simulate_dense_with_external_series
from augur.sim.slice import slice_dense_result

DEFAULT_MAX_CACHE_ROLLOUTS = 25_000


@dataclass(frozen=True)
class _CachedRollout:
    dense: DenseSimulationResult  # R=1
    exogenous_model_id: str


@dataclass(frozen=True)
class _DecodedRollout:
    seed: int
    monthly_metrics: pl.DataFrame
    terminal_metrics: TerminalMetrics
    cached: _CachedRollout

    @property
    def failed(self) -> bool:
        return self.terminal_metrics.failed_month_index is not None


class ProductService:
    def __init__(
        self,
        *,
        portfolio: PortfolioConfig,
        initial_cash_usd: float,
        primary_agent_id: str,
        known_location_ids: frozenset[str],
        properties_by_id: dict[str, Property],
        exogenous_model: Sampler,
        max_rollout_samples: int,
        max_cache_rollouts: int = DEFAULT_MAX_CACHE_ROLLOUTS,
    ) -> None:
        if max_cache_rollouts <= 0:
            raise ValueError("max_cache_rollouts must be positive")
        self._portfolio = portfolio
        self._initial_cash_usd = float(initial_cash_usd)
        self._primary_agent_id = primary_agent_id
        self._known_location_ids = known_location_ids
        self._properties_by_id = properties_by_id
        self._exogenous_model = exogenous_model
        self._max_rollout_samples = int(max_rollout_samples)
        self._max_cache_rollouts = int(max_cache_rollouts)
        self._initial_lots = initial_lots_from_portfolio(portfolio, primary_agent_id=primary_agent_id)
        self._asset_label_by_id = asset_label_by_series_id(portfolio)
        self._cache: OrderedDict[tuple[ScenarioKey, int], _CachedRollout] = OrderedDict()

    def metric_fan(self, request: MetricFanRequest) -> MetricFanResponse:
        if request.rollout_count > self._max_rollout_samples:
            raise ValueError(f"rollout count {request.rollout_count} exceeds max {self._max_rollout_samples}")
        decoded = self._decoded_rollouts(request.scenario, tuple(int(seed) for seed in request.rollout_seeds))
        exogenous_model_id = decoded[0].cached.exogenous_model_id if decoded else request.scenario.exogenous_model_id
        percentiles = tuple(float(pct) for pct in request.percentiles)
        return MetricFanResponse(
            exogenous_model_id=exogenous_model_id,
            metric=request.metric,
            monthly_metric_fan=_monthly_metric_fan(decoded, metric=request.metric, percentiles=percentiles),
            terminal_metric_percentiles=_terminal_metric_percentiles(
                decoded, metric=request.metric, percentiles=percentiles
            ),
            rollout_summaries=_rollout_summaries(decoded),
            failed_count=sum(1 for rollout in decoded if rollout.failed),
        )

    def rollout(self, request: RolloutRequest) -> RolloutResponse:
        [decoded] = self._decoded_rollouts(request.scenario, (int(request.seed),))
        events = rollout_events_from(
            decoded.cached.dense.decode(),
            primary_agent_id=self._primary_agent_id,
            asset_label_by_id=self._asset_label_by_id,
        )
        return RolloutResponse(
            exogenous_model_id=decoded.cached.exogenous_model_id,
            rollout=RolloutOutput(
                seed=decoded.seed,
                failed=decoded.failed,
                monthly_metrics=decoded.monthly_metrics.to_dict(as_series=False),
                terminal_metrics=decoded.terminal_metrics,
                events=events,
            ),
        )

    def _decoded_rollouts(self, scenario_key: ScenarioKey, seeds: tuple[int, ...]) -> tuple[_DecodedRollout, ...]:
        if scenario_key.exogenous_model_id != "current_exogenous_model":
            raise ValueError(f"unsupported exogenous_model_id: {scenario_key.exogenous_model_id!r}")
        if (
            scenario_key.rental_location_id is not None
            and scenario_key.rental_location_id not in self._known_location_ids
        ):
            raise ValueError(f"unknown rental_location_id: {scenario_key.rental_location_id!r}")
        if (
            scenario_key.property_purchase is not None
            and scenario_key.property_purchase.property_id not in self._properties_by_id
        ):
            raise ValueError(f"unknown property_id: {scenario_key.property_purchase.property_id!r}")
        cached_by_seed: dict[int, _CachedRollout] = {}
        missing: list[int] = []
        for seed in seeds:
            entry = self._cache_get(scenario_key, seed)
            if entry is None:
                missing.append(seed)
            else:
                cached_by_seed[seed] = entry
        if missing:
            fresh = self._simulate_missing(scenario_key, tuple(missing))
            for seed, entry in fresh.items():
                cached_by_seed[seed] = entry
                self._cache_put(scenario_key, seed, entry)
        decoded: list[_DecodedRollout] = []
        for seed in seeds:
            cached = cached_by_seed[seed]
            monthly = monthly_metrics_for_rollout(cached.dense, primary_agent_id=self._primary_agent_id)
            terminal = terminal_metrics_from(monthly, failed_month_index=failed_month_index_for_rollout(cached.dense))
            decoded.append(
                _DecodedRollout(seed=seed, monthly_metrics=monthly, terminal_metrics=terminal, cached=cached)
            )
        return tuple(decoded)

    def _simulate_missing(self, scenario_key: ScenarioKey, seeds: tuple[int, ...]) -> dict[int, _CachedRollout]:
        scenario = build_scenario(
            scenario_key,
            primary_agent_id=self._primary_agent_id,
            initial_cash_usd=self._initial_cash_usd,
            initial_lots=self._initial_lots,
            properties_by_id=self._properties_by_id,
        )
        sampled = self._exogenous_model.sample(
            ExogenousSamplingRequest(
                horizon_months=int(scenario_key.horizon_months),
                rollout_seeds=seeds,
                required_level_series=required_level_series(
                    scenario_key, initial_lots=self._initial_lots, properties_by_id=self._properties_by_id
                ),
            )
        )
        sampled = anchor_sampled_series_levels(sampled, self._portfolio.level_anchors)
        dense = simulate_dense_with_external_series(
            scenario, rollout_count=len(seeds), external_series=materialize_sampled_exogenous(sampled)
        )
        exogenous_model_id = str(sampled.metadata.get("exogenous_model_id") or scenario_key.exogenous_model_id)
        return {
            seed: _CachedRollout(
                dense=slice_dense_result(dense, rollout_index=batch_index), exogenous_model_id=exogenous_model_id
            )
            for batch_index, seed in enumerate(seeds)
        }

    def _cache_get(self, scenario_key: ScenarioKey, seed: int) -> _CachedRollout | None:
        key = (scenario_key, seed)
        entry = self._cache.get(key)
        if entry is None:
            return None
        self._cache.move_to_end(key)
        return entry

    def _cache_put(self, scenario_key: ScenarioKey, seed: int, entry: _CachedRollout) -> None:
        key = (scenario_key, seed)
        self._cache[key] = entry
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_cache_rollouts:
            self._cache.popitem(last=False)


def _monthly_metric_fan(
    rollouts: tuple[_DecodedRollout, ...], *, metric: MetricName, percentiles: tuple[float, ...]
) -> Frame:
    matrix = _metric_matrix(rollouts, metric=metric)
    if matrix is None:
        return {"month_index": [], "percentile": [], "value": []}
    month_indices, values = matrix
    percentile_values = _percentile(values, percentiles, axis=0)
    percentile_array = np.asarray(percentiles, dtype=np.float64)
    return {
        "month_index": np.repeat(month_indices, percentile_array.size).tolist(),
        "percentile": np.tile(percentile_array, month_indices.size).tolist(),
        "value": percentile_values.T.reshape(-1).tolist(),
    }


def _terminal_metric_percentiles(
    rollouts: tuple[_DecodedRollout, ...], *, metric: MetricName, percentiles: tuple[float, ...]
) -> Frame:
    values = np.asarray(
        [_terminal_metric_value(rollout.terminal_metrics, metric) for rollout in rollouts], dtype=np.float64
    )
    if values.size == 0:
        return {"percentile": [], "value": []}
    percentile_array = np.asarray(percentiles, dtype=np.float64)
    percentile_values = _percentile(values, percentiles, axis=0)
    return {"percentile": percentile_array.tolist(), "value": percentile_values.tolist()}


def _metric_matrix(
    rollouts: tuple[_DecodedRollout, ...], *, metric: MetricName
) -> tuple[np.ndarray, np.ndarray] | None:
    if not rollouts:
        return None
    month_indices = rollouts[0].monthly_metrics["month_index"].to_numpy().astype(np.int64, copy=False)
    values = np.empty((len(rollouts), month_indices.size), dtype=np.float64)
    for rollout_index, rollout in enumerate(rollouts):
        rollout_months = rollout.monthly_metrics["month_index"].to_numpy().astype(np.int64, copy=False)
        if rollout_months.shape != month_indices.shape or not np.array_equal(rollout_months, month_indices):
            raise ValueError("metric fan rollouts have inconsistent month indices")
        values[rollout_index] = rollout.monthly_metrics[metric].to_numpy().astype(np.float64, copy=False)
    return month_indices, values


def _percentile(values: np.ndarray, percentiles: tuple[float, ...], *, axis: int) -> np.ndarray:
    return cast(
        np.ndarray, np.percentile(values, np.asarray(percentiles, dtype=np.float64), axis=axis, method="linear")
    )


def _terminal_metric_value(terminal: TerminalMetrics, metric: MetricName) -> float:
    match metric:
        case "cash_usd":
            return terminal.cash_usd
        case "holding_value_usd":
            return terminal.holding_value_usd
        case "property_value_usd":
            return terminal.property_value_usd
        case "mortgage_balance_usd":
            return terminal.mortgage_balance_usd
        case "home_equity_usd":
            return terminal.home_equity_usd
        case "liquid_net_worth_usd":
            return terminal.liquid_net_worth_usd
        case "net_worth_usd":
            return terminal.net_worth_usd
        case "shortfall_usd":
            return terminal.shortfall_usd


def _rollout_summaries(rollouts: tuple[_DecodedRollout, ...]) -> tuple[RolloutSummary, ...]:
    sorted_rollouts = sorted(rollouts, key=_rollout_sort_key)
    count = len(sorted_rollouts)
    return tuple(
        RolloutSummary(
            seed=rollout.seed,
            failed=rollout.failed,
            terminal_metrics=rollout.terminal_metrics,
            sort_rank=rank,
            rank_percentile=((rank + 0.5) / count * 100) if count else 50.0,
        )
        for rank, rollout in enumerate(sorted_rollouts)
    )


def _rollout_sort_key(rollout: _DecodedRollout) -> tuple[bool, int, float, int]:
    terminal = rollout.terminal_metrics
    failed_month = terminal.failed_month_index if terminal.failed_month_index is not None else 10**9
    return (not rollout.failed, failed_month, terminal.net_worth_usd, rollout.seed)
