"""External-series wrangling: collect referenced series IDs from a scenario, and
build the dense `(series, rollout, month)` cubes the engine reads at runtime.

Separated from the orchestrator so the compile_simulation function in
`compiler/plan.py` reads as pure scaffolding and the per-domain compilers can
import these helpers directly when they need to encode `SeriesIndexedAmount`
fields."""

from __future__ import annotations

from typing import Any

import numpy as np

from augur.sim.external_series import ExternalSeriesContext
from augur.sim.scenario import Scenario, SeriesIndexedAmount


def collect_series_ids(scenario: Scenario, external_series: ExternalSeriesContext) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(series_id: str) -> None:
        if series_id not in seen:
            seen.add(series_id)
            ids.append(series_id)

    for value in external_series.series_values.select("series_id").unique().get_column("series_id").to_list():
        add(str(value))
    for transfer in [*scenario.scheduled_transfers, *scenario.recurring_transfers]:
        _add_amount_series_id(transfer.amount_usd, add)
    for obligation in [*scenario.scheduled_obligations, *scenario.recurring_obligations]:
        _add_amount_series_id(obligation.amount_due_usd, add)
    for sale in scenario.scheduled_asset_sales:
        if sale.price_per_unit_usd is None:
            add(sale.asset_id)
    for policy in scenario.liquidity_policies:
        for asset_id in policy.asset_preference_chain:
            add(asset_id)
    return tuple(ids)


def _add_amount_series_id(amount: Any, add: Any) -> None:
    if isinstance(amount, SeriesIndexedAmount):
        add(amount.series_id)


def external_values_cube(
    external_series: ExternalSeriesContext,
    *,
    series_index_by_id: dict[str, int],
    rollout_count: int,
    horizon_months: int,
) -> np.ndarray:
    values = np.full((len(series_index_by_id), rollout_count, horizon_months + 1), np.nan, dtype=np.float64)
    if external_series.series_values.is_empty():
        return values
    for row in external_series.series_values.iter_rows(named=True):
        series_index = series_index_by_id.get(str(row["series_id"]))
        if series_index is None:
            continue
        rollout_index = int(row["rollout_index"])
        month_index = int(row["month_index"])
        if 0 <= rollout_index < rollout_count and 0 <= month_index <= horizon_months:
            values[series_index, rollout_index, month_index] = float(row["value"])
    return values


def external_event_values_cube(
    external_series: ExternalSeriesContext,
    *,
    event_index_by_id: dict[str, int],
    rollout_count: int,
    horizon_months: int,
) -> np.ndarray:
    """Dense (event_count, rollout, month+1) boolean cube of sampled exogenous events."""

    values = np.zeros((max(1, len(event_index_by_id)), rollout_count, horizon_months + 1), dtype=np.bool_)
    if external_series.series_events.is_empty():
        return values
    for row in external_series.series_events.iter_rows(named=True):
        event_index = event_index_by_id.get(str(row["event_id"]))
        if event_index is None:
            continue
        rollout_index = int(row["rollout_index"])
        month_index = int(row["month_index"])
        if 0 <= rollout_index < rollout_count and 0 <= month_index <= horizon_months:
            values[event_index, rollout_index, month_index] = bool(row["active"])
    return values
