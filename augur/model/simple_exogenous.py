"""Sim-native simple exogenous path model for deployment placeholders."""

from __future__ import annotations

import numpy as np
from pydantic import Field

from augur.frames import concat_frames
from augur.model.deterministic import Constant
from augur.model.exogenous import (
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_events_frame,
)
from augur.model.gbm import GeometricBrownian
from augur.model.schemas import FrozenModel
from augur.model.series import (
    CRYPTO_SERIES_PREFIX,
    HOME_VALUE_SERIES_PREFIX,
    INFLATION_SERIES_ID,
    PRIVATE_EQUITY_SALE_EVENT_PREFIX,
    PRIVATE_EQUITY_SERIES_PREFIX,
    RENT_SERIES_PREFIX,
    SP500_SERIES_ID,
    series_suffix,
)
from augur.model.series_model import IndependentSeriesModels, ScalarSeriesSpec, derive_stream_rollout_seeds


class SimpleLocationModelParams(FrozenModel):
    """Per-location annual adjustment layered on top of simple GBM paths."""

    home_value_annual_adjustment_pct: float = 0.0
    rent_annual_adjustment_pct: float = 0.0


class SimpleExogenousModelConfig(FrozenModel):
    """Deployment-supplied parameters for `SimpleExogenousModel`."""

    location_params: dict[str, SimpleLocationModelParams] = Field(default_factory=dict)


class SimpleExogenousModel(FrozenModel):
    """Small sim-native stochastic model used until calibrated models plug in."""

    current_private_equity_price_usd: float = Field(default=0.0, ge=0.0)
    parameters: SimpleExogenousModelConfig = Field(default_factory=SimpleExogenousModelConfig)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        levels = (
            IndependentSeriesModels(series=self._level_models(request.required_level_series)).sample(request).levels
        )
        event_blocks = [
            series_events_frame(
                event_id,
                self._sample_event_series(event_id, request),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for event_id in sorted(request.required_event_series)
        ]
        return SampledExogenousBundle(
            levels=concat_frames([levels], SERIES_LEVELS_SCHEMA),
            events=concat_frames(event_blocks, SERIES_EVENTS_SCHEMA),
            metadata={
                "exogenous_model_id": "simple_exogenous_model",
                "current_private_equity_price_usd": self.current_private_equity_price_usd,
            },
        )

    def _level_models(self, series_ids: frozenset[str]) -> dict[str, ScalarSeriesSpec]:
        return {series_id: self._level_model(series_id) for series_id in sorted(series_ids)}

    def _level_model(self, series_id: str) -> ScalarSeriesSpec:
        if series_id == INFLATION_SERIES_ID:
            return _simple_gbm_level(annual_return_pct=3.0, annual_volatility_pct=1.5)
        if series_id == SP500_SERIES_ID:
            return _simple_gbm_level(annual_return_pct=7.0, annual_volatility_pct=16.0)
        if location_id := series_suffix(series_id, HOME_VALUE_SERIES_PREFIX):
            params = self.parameters.location_params.get(location_id, SimpleLocationModelParams())
            return _simple_gbm_level(
                annual_return_pct=3.5,
                annual_volatility_pct=8.0,
                annual_adjustment_pct=params.home_value_annual_adjustment_pct,
            )
        if location_id := series_suffix(series_id, RENT_SERIES_PREFIX):
            params = self.parameters.location_params.get(location_id, SimpleLocationModelParams())
            return _simple_gbm_level(
                annual_return_pct=3.0,
                annual_volatility_pct=3.0,
                annual_adjustment_pct=params.rent_annual_adjustment_pct,
            )
        if series_suffix(series_id, PRIVATE_EQUITY_SERIES_PREFIX) is not None:
            return _simple_gbm_level(
                initial_value=self.current_private_equity_price_usd or 1.0,
                annual_return_pct=8.0,
                annual_volatility_pct=35.0,
            )
        if series_suffix(series_id, CRYPTO_SERIES_PREFIX) is not None:
            return Constant(value=1.0)
        raise ValueError(f"simple exogenous model cannot sample level series {series_id!r}")

    def _sample_event_series(self, event_id: str, request: ExogenousSamplingRequest) -> np.ndarray:
        if series_suffix(event_id, PRIVATE_EQUITY_SALE_EVENT_PREFIX) is not None:
            return _private_equity_sale_events(
                rollout_seeds=derive_stream_rollout_seeds(request.rollout_seeds, stream_id=event_id),
                horizon_months=request.horizon_months,
            )
        raise ValueError(f"simple exogenous model cannot sample event series {event_id!r}")


def _simple_gbm_level(
    *,
    annual_return_pct: float,
    annual_volatility_pct: float,
    initial_value: float = 1.0,
    annual_adjustment_pct: float = 0.0,
) -> GeometricBrownian:
    monthly_sigma = annual_volatility_pct / 100 / np.sqrt(12)
    monthly_mu = annual_return_pct / 100 / 12 - 0.5 * monthly_sigma**2 + np.log1p(annual_adjustment_pct / 100) / 12
    return GeometricBrownian(
        initial_value=initial_value, monthly_log_return_mu=monthly_mu, monthly_log_return_sigma=monthly_sigma
    )


def _private_equity_sale_events(*, rollout_seeds: tuple[int, ...], horizon_months: int) -> np.ndarray:
    events = np.zeros((len(rollout_seeds), horizon_months + 1), dtype=np.bool_)
    if horizon_months < 12:
        return events
    for rollout_index, seed in enumerate(rollout_seeds):
        events[rollout_index, 1:] = np.random.default_rng(seed).random(horizon_months) < (1 / 72)
    return events
