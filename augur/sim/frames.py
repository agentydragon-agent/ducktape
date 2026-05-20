"""Shared helpers for typed Polars frames."""

from __future__ import annotations

from collections.abc import Iterable

import polars as pl


def concat_frames(frames: Iterable[pl.DataFrame], schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Concatenate frames while preserving the typed empty case."""

    return pl.concat([pl.DataFrame(schema=schema), *frames]).select(list(schema.keys()))
