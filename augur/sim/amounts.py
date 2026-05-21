"""Coerce legacy scalar amounts before evaluating configured amount schedules."""

from __future__ import annotations

import polars as pl

from augur.sim.external_series import ExternalSeriesContext
from augur.sim.scenario import AmountSpec, FixedAmount, SeriesIndexedAmount


def amount_by_rollout(
    amount: AmountSpec, *, external_series: ExternalSeriesContext, rollouts: pl.DataFrame, month: int, column_name: str
) -> pl.DataFrame:
    """Return `(rollout_index, column_name)` for a configured amount."""

    schedule = (
        amount if isinstance(amount, (FixedAmount, SeriesIndexedAmount)) else FixedAmount(amount_usd=float(amount))
    )
    return schedule.amount_by_rollout(
        external_series=external_series, rollouts=rollouts, month=month, column_name=column_name
    )
