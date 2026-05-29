"""Reusable model fixtures for product/API tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from augur.frames import concat_frames
from augur.model.exogenous import (
    SERIES_LEVELS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_levels_frame,
)
from augur.model.private_equity_bundle import (
    PrivateEquityBoolChannel,
    PrivateEquityBundle,
    PrivateEquityFloatChannel,
    PrivateEquityIntChannel,
)
from augur.model.series import LevelSeriesKey, PrivateEquityEventKindCode, PrivateEquityRegimeCode

type LevelOverride = float | npt.NDArray[np.float64] | Callable[[ExogenousSamplingRequest], npt.NDArray[np.float64]]
type IntOverride = int | npt.NDArray[np.int64] | Callable[[ExogenousSamplingRequest], npt.NDArray[np.int64]]
type EventOverride = bool | npt.NDArray[np.bool_] | Callable[[ExogenousSamplingRequest], npt.NDArray[np.bool_]]

# Default values for each float PE channel when no override is provided.
_PE_FLOAT_DEFAULTS: dict[PrivateEquityFloatChannel, float] = {
    PrivateEquityFloatChannel.SALE_CAPACITY_FRACTION: 1.0,
    PrivateEquityFloatChannel.ELIGIBLE_FRACTION: 1.0,
    PrivateEquityFloatChannel.FORCED_SALE_FRACTION: 0.0,
    PrivateEquityFloatChannel.FORCED_RECOVERY_CASHOUT_USD: 0.0,
}


@dataclass
class ConstantFrameExogenousModel:
    """Constant-frame fixture sampler.

    `level_overrides` / `event_overrides` key on the wire-form series id of
    non-PE series. PE channels go through three separate, dtype-typed maps
    keyed on `(issuer_id, channel)` — no value-type union, no coercion at
    construction time.
    """

    level_overrides: Mapping[LevelSeriesKey, LevelOverride] = field(default_factory=dict)
    private_equity_float_overrides: Mapping[tuple[str, PrivateEquityFloatChannel], LevelOverride] = field(
        default_factory=dict
    )
    private_equity_int_overrides: Mapping[tuple[str, PrivateEquityIntChannel], IntOverride] = field(
        default_factory=dict
    )
    private_equity_bool_overrides: Mapping[tuple[str, PrivateEquityBoolChannel], EventOverride] = field(
        default_factory=dict
    )
    default_level_value: float = 1.0
    metadata: Mapping[str, object] = field(default_factory=lambda: {"exogenous_model_id": "constant_frame_fixture"})
    sample_requests: list[ExogenousSamplingRequest] = field(default_factory=list)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        self.sample_requests.append(request)
        levels = [
            series_levels_frame(
                key,
                _level_matrix(self.level_overrides.get(key, self.default_level_value), request),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for key in sorted(request.required_level_series, key=lambda key: key.wire_id)
        ]
        pe_bundle_parts = [
            _build_pe_bundle_part(self, issuer_id, request)
            for issuer_id in sorted(request.required_private_equity_issuers)
        ]
        private_equity_bundle = (
            PrivateEquityBundle.combine(pe_bundle_parts) if pe_bundle_parts else PrivateEquityBundle.empty()
        )
        return SampledExogenousBundle(
            levels=concat_frames(levels, SERIES_LEVELS_SCHEMA),
            private_equity=private_equity_bundle,
            metadata=dict(self.metadata),
        )


def _build_pe_bundle_part(
    fixture: ConstantFrameExogenousModel, issuer_id: str, request: ExogenousSamplingRequest
) -> PrivateEquityBundle:
    """Build a single-issuer `PrivateEquityBundle` from the typed override maps."""

    expected_shape = (request.rollout_count, request.horizon_months + 1)

    def float_channel(channel: PrivateEquityFloatChannel, default: float) -> npt.NDArray[np.float64]:
        override = fixture.private_equity_float_overrides.get((issuer_id, channel))
        if override is None:
            return np.full(expected_shape, default, dtype=np.float64)
        return _level_matrix(override, request)

    def int_channel(channel: PrivateEquityIntChannel, default: int | npt.NDArray[np.int64]) -> npt.NDArray[np.int64]:
        override = fixture.private_equity_int_overrides.get((issuer_id, channel))
        if override is None:
            return _broadcast_int_default(default, request)
        return _int_matrix(override, request)

    def bool_channel(channel: PrivateEquityBoolChannel, default: bool) -> npt.NDArray[np.bool_]:
        override = fixture.private_equity_bool_overrides.get((issuer_id, channel))
        if override is None:
            return np.full(expected_shape, default, dtype=np.bool_)
        return _event_matrix(override, request)

    tender_events = bool_channel(PrivateEquityBoolChannel.SALE_OPPORTUNITY_ACTIVE, False)
    event_kind_default = np.where(
        tender_events, int(PrivateEquityEventKindCode.TENDER), int(PrivateEquityEventKindCode.NONE)
    ).astype(np.int64)
    return PrivateEquityBundle.from_issuer_arrays(
        issuer_id,
        mark_usd_per_unit=float_channel(PrivateEquityFloatChannel.MARK_USD_PER_UNIT, fixture.default_level_value),
        regime_code=int_channel(PrivateEquityIntChannel.REGIME_CODE, int(PrivateEquityRegimeCode.PRIVATE_OPERATING)),
        event_kind_code=int_channel(PrivateEquityIntChannel.EVENT_KIND_CODE, event_kind_default),
        sale_opportunity_active=tender_events,
        sale_capacity_fraction=float_channel(
            PrivateEquityFloatChannel.SALE_CAPACITY_FRACTION,
            _PE_FLOAT_DEFAULTS[PrivateEquityFloatChannel.SALE_CAPACITY_FRACTION],
        ),
        eligible_fraction=float_channel(
            PrivateEquityFloatChannel.ELIGIBLE_FRACTION, _PE_FLOAT_DEFAULTS[PrivateEquityFloatChannel.ELIGIBLE_FRACTION]
        ),
        forced_sale_fraction=float_channel(
            PrivateEquityFloatChannel.FORCED_SALE_FRACTION,
            _PE_FLOAT_DEFAULTS[PrivateEquityFloatChannel.FORCED_SALE_FRACTION],
        ),
        liquidity_blocked=bool_channel(PrivateEquityBoolChannel.LIQUIDITY_BLOCKED, False),
        forced_recovery_cashout_usd=float_channel(
            PrivateEquityFloatChannel.FORCED_RECOVERY_CASHOUT_USD,
            _PE_FLOAT_DEFAULTS[PrivateEquityFloatChannel.FORCED_RECOVERY_CASHOUT_USD],
        ),
        rollout_count=request.rollout_count,
        horizon_months=request.horizon_months,
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


def event_matrix_with_step(*, default: bool, override: bool, month: int) -> EventOverride:
    def build(request: ExogenousSamplingRequest) -> npt.NDArray[np.bool_]:
        matrix = np.full((request.rollout_count, request.horizon_months + 1), default, dtype=np.bool_)
        matrix[:, min(month, request.horizon_months) :] = override
        return matrix

    return build


def int_matrix_with_month_override(*, default: int, override: int, month: int) -> IntOverride:
    def build(request: ExogenousSamplingRequest) -> npt.NDArray[np.int64]:
        matrix = np.full((request.rollout_count, request.horizon_months + 1), default, dtype=np.int64)
        matrix[:, min(month, request.horizon_months)] = override
        return matrix

    return build


def int_matrix_with_step(*, default: int, override: int, month: int) -> IntOverride:
    def build(request: ExogenousSamplingRequest) -> npt.NDArray[np.int64]:
        matrix = np.full((request.rollout_count, request.horizon_months + 1), default, dtype=np.int64)
        matrix[:, min(month, request.horizon_months) :] = override
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


def _int_matrix(value: IntOverride, request: ExogenousSamplingRequest) -> npt.NDArray[np.int64]:
    raw = value(request) if callable(value) else value
    matrix = (
        np.asarray(raw, dtype=np.int64)
        if isinstance(raw, np.ndarray)
        else np.full((request.rollout_count, request.horizon_months + 1), int(raw), dtype=np.int64)
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


def _broadcast_int_default(
    default: int | npt.NDArray[np.int64], request: ExogenousSamplingRequest
) -> npt.NDArray[np.int64]:
    matrix = (
        np.asarray(default, dtype=np.int64)
        if isinstance(default, np.ndarray)
        else np.full((request.rollout_count, request.horizon_months + 1), int(default), dtype=np.int64)
    )
    _check_shape(matrix, request)
    return matrix


def _check_shape(matrix: np.ndarray, request: ExogenousSamplingRequest) -> None:
    expected = (request.rollout_count, request.horizon_months + 1)
    if matrix.shape != expected:
        raise ValueError(f"constant fixture matrix has shape {matrix.shape}; expected {expected}")
