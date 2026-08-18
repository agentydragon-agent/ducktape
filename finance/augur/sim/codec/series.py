"""Decode the external level series into the run's flat, wire-keyed read model.

The compile path is typed by `LevelSeriesKey` end to end (see
`sim/external_series.py`). This is the other end: the decoded frames a caller
joins and serializes, where every entity is already identified by its wire
string — `asset_lots.asset_id`, product wire events. A price frame keyed the
same way is what makes `run.asset_lots ⋈ run.series_values` a join rather than
a lookup table, so the wire id here is the serialization boundary doing its
job, not a shim around a missing type.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from finance.augur.frames import FrameSpec, concat_frames
from finance.augur.model.exogenous import LevelFrames
from finance.augur.sim.compiler import CompiledSimulation

SERIES_VALUES_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value": pl.Float64()}
)
SERIES_VALUES_FRAME = FrameSpec("series_values", SERIES_VALUES_SCHEMA)
MONEY_SERIES_VALUES_SCHEMA = pl.Schema(
    {"rollout_index": pl.Int64(), "month_index": pl.Int64(), "series_id": pl.Utf8(), "value_quanta": pl.Int64()}
)
MONEY_SERIES_VALUES_FRAME = FrameSpec("money_series_values", MONEY_SERIES_VALUES_SCHEMA)


def decode_series_values(levels: LevelFrames) -> pl.DataFrame:
    """Flatten heterogeneous model levels into `(rollout, month, series_id, value)` rows."""

    return concat_frames(
        [
            frame.with_columns(pl.lit(key.wire_id, dtype=pl.Utf8()).alias("series_id")).select(
                SERIES_VALUES_SCHEMA.names()
            )
            for key, frame in levels.value_rows()
        ],
        SERIES_VALUES_SCHEMA,
    )


def decode_money_series_values(plan: CompiledSimulation) -> pl.DataFrame:
    """Flatten the compiler's exact sampled-money cube for decoded valuations.

    `series_values` intentionally retains heterogeneous float model levels: it
    contains rates and index ratios as well as price paths. Consumers that
    value a holding must use this companion frame instead, so decoded values
    cannot reintroduce a float money boundary after the engine quantized it.
    """

    series_count, rollout_count, month_count = plan.external_money_values.shape
    if series_count == 0 or rollout_count == 0:
        return MONEY_SERIES_VALUES_FRAME.empty()
    series_indices = np.broadcast_to(
        np.arange(series_count, dtype=np.int64)[:, None, None], (series_count, rollout_count, month_count)
    ).reshape(-1)
    rollout_indices = np.broadcast_to(
        np.arange(rollout_count, dtype=np.int64)[None, :, None], (series_count, rollout_count, month_count)
    ).reshape(-1)
    month_indices = np.broadcast_to(
        np.arange(month_count, dtype=np.int64)[None, None, :], (series_count, rollout_count, month_count)
    ).reshape(-1)
    series_ids = np.asarray([key.wire_id for key in plan.series_keys], dtype=object)[series_indices]
    return MONEY_SERIES_VALUES_FRAME.normalize(
        pl.DataFrame(
            {
                "rollout_index": rollout_indices,
                "month_index": month_indices,
                "series_id": series_ids,
                "value_quanta": plan.external_money_values.reshape(-1).astype(np.int64, copy=False),
            }
        )
    )
