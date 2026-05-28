"""Reusable model fixtures for product/API tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from augur.frames import concat_frames
from augur.model.exogenous import (
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_events_frame,
    series_levels_frame,
)

type LevelOverride = float | npt.NDArray[np.float64] | Callable[[ExogenousSamplingRequest], npt.NDArray[np.float64]]
type EventOverride = bool | npt.NDArray[np.bool_] | Callable[[ExogenousSamplingRequest], npt.NDArray[np.bool_]]


@dataclass
class ConstantFrameExogenousModel:
    level_overrides: Mapping[str, LevelOverride] = field(default_factory=dict)
    event_overrides: Mapping[str, EventOverride] = field(default_factory=dict)
    default_level_value: float = 1.0
    default_event_active: bool = False
    metadata: Mapping[str, object] = field(default_factory=lambda: {"exogenous_model_id": "constant_frame_fixture"})
    sample_requests: list[ExogenousSamplingRequest] = field(default_factory=list)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        self.sample_requests.append(request)
        levels = [
            series_levels_frame(
                series_id,
                _level_matrix(self.level_overrides.get(series_id, self.default_level_value), request),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for series_id in sorted(request.required_level_series)
        ]
        events = [
            series_events_frame(
                event_id,
                _event_matrix(self.event_overrides.get(event_id, self.default_event_active), request),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for event_id in sorted(request.required_event_series)
        ]
        return SampledExogenousBundle(
            levels=concat_frames(levels, SERIES_LEVELS_SCHEMA),
            events=concat_frames(events, SERIES_EVENTS_SCHEMA),
            metadata=dict(self.metadata),
        )


def level_matrix_with_month_override(*, default: float, override: float, month: int) -> LevelOverride:
    def build(request: ExogenousSamplingRequest) -> npt.NDArray[np.float64]:
        matrix = np.full((request.rollout_count, request.horizon_months + 1), default, dtype=np.float64)
        matrix[:, min(month, request.horizon_months)] = override
        return matrix

    return build


def _level_matrix(value: LevelOverride, request: ExogenousSamplingRequest) -> npt.NDArray[np.float64]:
    raw = value(request) if callable(value) else value
    matrix = (
        np.asarray(raw, dtype=np.float64)
        if isinstance(raw, np.ndarray)
        else np.full((request.rollout_count, request.horizon_months + 1), float(raw), dtype=np.float64)
    )
    _check_shape(matrix, request)
    return matrix


def _event_matrix(value: EventOverride, request: ExogenousSamplingRequest) -> npt.NDArray[np.bool_]:
    raw = value(request) if callable(value) else value
    matrix = (
        np.asarray(raw, dtype=np.bool_)
        if isinstance(raw, np.ndarray)
        else np.full((request.rollout_count, request.horizon_months + 1), bool(raw), dtype=np.bool_)
    )
    _check_shape(matrix, request)
    return matrix


def _check_shape(matrix: np.ndarray, request: ExogenousSamplingRequest) -> None:
    expected = (request.rollout_count, request.horizon_months + 1)
    if matrix.shape != expected:
        raise ValueError(f"constant fixture matrix has shape {matrix.shape}; expected {expected}")
