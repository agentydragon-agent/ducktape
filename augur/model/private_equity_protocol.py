"""Private-equity protocol series materialization helpers."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import polars as pl

from augur.model.exogenous import PRIVATE_EQUITY_PROTOCOL_SCHEMA, series_levels_frame
from augur.model.series import (
    PrivateEquityEventKindCode,
    PrivateEquityRegimeCode,
    private_equity_eligible_fraction_series_id,
    private_equity_event_kind_code_series_id,
    private_equity_forced_recovery_cashout_usd_series_id,
    private_equity_forced_sale_fraction_series_id,
    private_equity_liquidity_blocked_series_id,
    private_equity_regime_code_series_id,
    private_equity_sale_capacity_fraction_series_id,
)

BoolMatrix = npt.NDArray[np.bool_]
CodeMatrix = npt.NDArray[np.int64]
FloatMatrix = npt.NDArray[np.float64]


def observed_private_equity_mark_matrix(latent_mark: FloatMatrix, update_events: BoolMatrix) -> FloatMatrix:
    """Expose private marks only at observed update events.

    Before public-market trading exists, the sampled latent issuer value is an internal
    driver. The user-visible PE mark is the last observed admin/tender value, forward
    filled between sparse update events.
    """

    if latent_mark.shape != update_events.shape:
        raise ValueError(
            f"private-equity latent mark matrix has shape {latent_mark.shape}; "
            f"expected update event shape {update_events.shape}"
        )
    if not np.isfinite(latent_mark).all() or np.any(latent_mark <= 0.0):
        raise ValueError("private-equity latent mark matrix must be finite and positive")

    observed = np.empty_like(latent_mark, dtype=np.float64)
    observed[:, 0] = latent_mark[:, 0]
    for month in range(1, latent_mark.shape[1]):
        observed[:, month] = np.where(update_events[:, month], latent_mark[:, month], observed[:, month - 1])
    return observed


def neutral_private_equity_auxiliary_level_frames(
    issuer_id: str, *, tender_events: BoolMatrix, rollout_count: int, horizon_months: int
) -> tuple[pl.DataFrame, ...]:
    """Return required PE auxiliary level series with neutral v1 behavior.

    These series make the richer PE protocol explicit even for models that only produce
    a continuous mark plus tender opportunities today. Neutral values preserve the old
    behavior: private operating regime, tender-kind markers on tender months, no
    liquidity block, full eligibility/capacity, and no forced-sale/recovery path.
    """

    expected_shape = (rollout_count, horizon_months + 1)
    if tender_events.shape != expected_shape:
        raise ValueError(f"tender event matrix has shape {tender_events.shape}; expected {expected_shape}")

    event_kind = np.where(tender_events, int(PrivateEquityEventKindCode.TENDER), int(PrivateEquityEventKindCode.NONE))
    return private_equity_auxiliary_level_frames(
        issuer_id,
        tender_events=tender_events,
        event_kind_code=event_kind,
        regime_code=np.full(expected_shape, int(PrivateEquityRegimeCode.PRIVATE_OPERATING), dtype=np.int64),
        sale_capacity_fraction=np.ones(expected_shape, dtype=np.float64),
        eligible_fraction=np.ones(expected_shape, dtype=np.float64),
        forced_sale_fraction=np.zeros(expected_shape, dtype=np.float64),
        liquidity_blocked=np.zeros(expected_shape, dtype=np.float64),
        forced_recovery_cashout_usd=np.zeros(expected_shape, dtype=np.float64),
        rollout_count=rollout_count,
        horizon_months=horizon_months,
    )


def neutral_private_equity_protocol_frame(
    issuer_id: str, *, tender_events: BoolMatrix, rollout_count: int, horizon_months: int
) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    _require_matrix(tender_events, expected_shape, "tender_events")
    event_kind_code = np.where(
        tender_events, int(PrivateEquityEventKindCode.TENDER), int(PrivateEquityEventKindCode.NONE)
    )
    return private_equity_protocol_frame(
        issuer_id,
        event_kind_code=event_kind_code,
        regime_code=np.full(expected_shape, int(PrivateEquityRegimeCode.PRIVATE_OPERATING), dtype=np.int64),
        rollout_count=rollout_count,
        horizon_months=horizon_months,
    )


def private_equity_protocol_frame(
    issuer_id: str, *, event_kind_code: CodeMatrix, regime_code: CodeMatrix, rollout_count: int, horizon_months: int
) -> pl.DataFrame:
    expected_shape = (rollout_count, horizon_months + 1)
    _require_code_matrix(event_kind_code, expected_shape, "event_kind_code")
    _require_code_matrix(regime_code, expected_shape, "regime_code")
    rollout_idx, month_idx = _long_indices(rollout_count=rollout_count, horizon_months=horizon_months)
    return pl.DataFrame(
        {
            "rollout_index": rollout_idx,
            "month_index": month_idx,
            "issuer_id": [issuer_id] * (rollout_count * (horizon_months + 1)),
            "regime_code": regime_code.reshape(-1),
            "event_kind_code": event_kind_code.reshape(-1),
        },
        schema=PRIVATE_EQUITY_PROTOCOL_SCHEMA,
    )


def private_equity_auxiliary_level_frames(
    issuer_id: str,
    *,
    tender_events: BoolMatrix,
    event_kind_code: CodeMatrix,
    regime_code: CodeMatrix,
    sale_capacity_fraction: FloatMatrix,
    eligible_fraction: FloatMatrix,
    forced_sale_fraction: FloatMatrix,
    liquidity_blocked: FloatMatrix,
    forced_recovery_cashout_usd: FloatMatrix,
    rollout_count: int,
    horizon_months: int,
) -> tuple[pl.DataFrame, ...]:
    expected_shape = (rollout_count, horizon_months + 1)
    _require_matrix(tender_events, expected_shape, "tender_events")
    _require_code_matrix(event_kind_code, expected_shape, "event_kind_code")
    _require_code_matrix(regime_code, expected_shape, "regime_code")
    _require_float_matrix(sale_capacity_fraction, expected_shape, "sale_capacity_fraction")
    _require_float_matrix(eligible_fraction, expected_shape, "eligible_fraction")
    _require_float_matrix(forced_sale_fraction, expected_shape, "forced_sale_fraction")
    _require_float_matrix(liquidity_blocked, expected_shape, "liquidity_blocked")
    _require_float_matrix(forced_recovery_cashout_usd, expected_shape, "forced_recovery_cashout_usd")

    return (
        series_levels_frame(
            private_equity_regime_code_series_id(issuer_id),
            regime_code.astype(np.float64),
            rollout_count=rollout_count,
            horizon_months=horizon_months,
        ),
        series_levels_frame(
            private_equity_event_kind_code_series_id(issuer_id),
            event_kind_code.astype(np.float64),
            rollout_count=rollout_count,
            horizon_months=horizon_months,
        ),
        series_levels_frame(
            private_equity_sale_capacity_fraction_series_id(issuer_id),
            sale_capacity_fraction,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
        ),
        series_levels_frame(
            private_equity_eligible_fraction_series_id(issuer_id),
            eligible_fraction,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
        ),
        series_levels_frame(
            private_equity_forced_sale_fraction_series_id(issuer_id),
            forced_sale_fraction,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
        ),
        series_levels_frame(
            private_equity_liquidity_blocked_series_id(issuer_id),
            liquidity_blocked,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
        ),
        series_levels_frame(
            private_equity_forced_recovery_cashout_usd_series_id(issuer_id),
            forced_recovery_cashout_usd,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
        ),
    )


def _require_matrix(value: np.ndarray, expected_shape: tuple[int, int], label: str) -> None:
    if value.shape != expected_shape:
        raise ValueError(f"private-equity {label} matrix has shape {value.shape}; expected {expected_shape}")


def _require_code_matrix(value: np.ndarray, expected_shape: tuple[int, int], label: str) -> None:
    _require_matrix(value, expected_shape, label)
    if not np.issubdtype(value.dtype, np.integer):
        raise ValueError(f"private-equity {label} matrix must have an integer dtype")


def _require_float_matrix(value: np.ndarray, expected_shape: tuple[int, int], label: str) -> None:
    _require_matrix(value, expected_shape, label)
    if not np.isfinite(value).all():
        raise ValueError(f"private-equity {label} matrix must be finite")


def _long_indices(*, rollout_count: int, horizon_months: int) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.repeat(np.arange(rollout_count, dtype=np.int64), horizon_months + 1),
        np.tile(np.arange(horizon_months + 1, dtype=np.int64), rollout_count),
    )
