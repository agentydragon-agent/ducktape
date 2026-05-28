"""Reusable model fixtures for product/API tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from augur.frames import concat_frames
from augur.model.exogenous import (
    PRIVATE_EQUITY_PROTOCOL_SCHEMA,
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_events_frame,
    series_levels_frame,
)
from augur.model.private_equity_protocol import private_equity_protocol_frame
from augur.model.series import (
    PrivateEquityEventKindCode,
    PrivateEquityRegimeCode,
    private_equity_event_kind_code_series_id,
    private_equity_regime_code_series_id,
    private_equity_sale_event_id,
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
        protocols = [
            private_equity_protocol_frame(
                issuer_id,
                event_kind_code=_code_matrix(
                    self.level_overrides.get(private_equity_event_kind_code_series_id(issuer_id)),
                    request,
                    default=_default_event_kind_code_matrix(self.event_overrides, issuer_id, request),
                ),
                regime_code=_code_matrix(
                    self.level_overrides.get(private_equity_regime_code_series_id(issuer_id)),
                    request,
                    default=int(PrivateEquityRegimeCode.PRIVATE_OPERATING),
                ),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for issuer_id in sorted(request.required_private_equity_protocol_issuers)
        ]
        return SampledExogenousBundle(
            levels=concat_frames(levels, SERIES_LEVELS_SCHEMA),
            events=concat_frames(events, SERIES_EVENTS_SCHEMA),
            private_equity_protocol=concat_frames(protocols, PRIVATE_EQUITY_PROTOCOL_SCHEMA),
            metadata=dict(self.metadata),
        )


def level_matrix_with_month_override(*, default: float, override: float, month: int) -> LevelOverride:
    def build(request: ExogenousSamplingRequest) -> npt.NDArray[np.float64]:
        matrix = np.full((request.rollout_count, request.horizon_months + 1), default, dtype=np.float64)
        matrix[:, min(month, request.horizon_months)] = override
        return matrix

    return build


def level_matrix_with_step(*, default: float, override: float, month: int) -> LevelOverride:
    def build(request: ExogenousSamplingRequest) -> npt.NDArray[np.float64]:
        matrix = np.full((request.rollout_count, request.horizon_months + 1), default, dtype=np.float64)
        matrix[:, min(month, request.horizon_months) :] = override
        return matrix

    return build


def event_matrix_with_month_override(*, default: bool, override: bool, month: int) -> EventOverride:
    def build(request: ExogenousSamplingRequest) -> npt.NDArray[np.bool_]:
        matrix = np.full((request.rollout_count, request.horizon_months + 1), default, dtype=np.bool_)
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


def _code_matrix(
    value: LevelOverride | None, request: ExogenousSamplingRequest, *, default: int | npt.NDArray[np.int64]
) -> npt.NDArray[np.int64]:
    if value is None:
        matrix = (
            np.asarray(default, dtype=np.int64)
            if isinstance(default, np.ndarray)
            else np.full((request.rollout_count, request.horizon_months + 1), int(default), dtype=np.int64)
        )
    else:
        raw_float = _level_matrix(value, request)
        rounded = np.rint(raw_float)
        if not np.array_equal(raw_float, rounded):
            raise ValueError("private-equity protocol fixture code override must contain integer values")
        matrix = rounded.astype(np.int64)
    _check_shape(matrix, request)
    return matrix


def _default_event_kind_code_matrix(
    event_overrides: Mapping[str, EventOverride], issuer_id: str, request: ExogenousSamplingRequest
) -> npt.NDArray[np.int64]:
    tender_events = _event_matrix(event_overrides.get(private_equity_sale_event_id(issuer_id), False), request)
    return np.where(tender_events, int(PrivateEquityEventKindCode.TENDER), int(PrivateEquityEventKindCode.NONE))


def _check_shape(matrix: np.ndarray, request: ExogenousSamplingRequest) -> None:
    expected = (request.rollout_count, request.horizon_months + 1)
    if matrix.shape != expected:
        raise ValueError(f"constant fixture matrix has shape {matrix.shape}; expected {expected}")
