"""Slice a batched DenseSimulationResult into a single-rollout (R=1) result."""

from __future__ import annotations

import dataclasses

import numpy as np
import polars as pl

from augur.sim.engine import DenseSimulationResult, SimulationBuffers
from augur.sim.external_series import ExternalSeriesContext


def slice_dense_result(dense: DenseSimulationResult, *, rollout_index: int) -> DenseSimulationResult:
    """Return an R=1 DenseSimulationResult for one rollout of a batched result.

    The cached slice owns its own memory (via `.copy()` on every array) so the
    source batch can be released."""
    plan = dataclasses.replace(
        dense.plan,
        rollout_count=1,
        slot_plan=dataclasses.replace(dense.plan.slot_plan, rollout_count=1),
        external_values=dense.plan.external_values[:, rollout_index : rollout_index + 1, :].copy(),
    )
    buffers = SimulationBuffers(
        state=_take_dc(dense.buffers.state, rollout_index, axis=-1),
        transfers=_take_dc(dense.buffers.transfers, rollout_index, axis=-1),
        properties=_take_dc(dense.buffers.properties, rollout_index, axis=-1),
        lot_dispositions=_take_dc(dense.buffers.lot_dispositions, rollout_index, axis=-1),
        taxes=_take_dc(dense.buffers.taxes, rollout_index, axis=-1),
        obligations=_take_dc(dense.buffers.obligations, rollout_index, axis=-1),
        lifecycle=_take_dc(dense.buffers.lifecycle, rollout_index, axis=-1),
    )
    external_series = ExternalSeriesContext(
        series_values=(
            dense.external_series.series_values.filter(pl.col("rollout_index") == rollout_index).with_columns(
                rollout_index=pl.lit(0, dtype=pl.Int64)
            )
        ),
        series_events=(
            dense.external_series.series_events.filter(pl.col("rollout_index") == rollout_index).with_columns(
                rollout_index=pl.lit(0, dtype=pl.Int64)
            )
            if not dense.external_series.series_events.is_empty()
            else dense.external_series.series_events
        ),
    )
    return DenseSimulationResult(plan=plan, buffers=buffers, external_series=external_series)


def _take_dc[T](obj: T, rollout_index: int, *, axis: int) -> T:
    fields = dataclasses.fields(obj)  # type: ignore[arg-type]
    sliced = {field.name: np.take(getattr(obj, field.name), [rollout_index], axis=axis).copy() for field in fields}
    return type(obj)(**sliced)
