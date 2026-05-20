"""Sim-native simple market model for deployment placeholders."""

from __future__ import annotations

import numpy as np
from pydantic import Field

from augur.core.schemas import ApiModel
from augur.frames import concat_frames
from augur.model.sim_market_api import (
    MARKET_EVENTS_SCHEMA,
    MARKET_LEVELS_SCHEMA,
    MarketSamplingRequest,
    SampledMarketBundle,
    market_events_frame,
    market_levels_frame,
)
from augur.model.sim_market_series import (
    CRYPTO_SERIES_PREFIX,
    HOME_VALUE_SERIES_PREFIX,
    INFLATION_SERIES_ID,
    PRIVATE_EQUITY_SALE_EVENT_PREFIX,
    PRIVATE_EQUITY_SERIES_PREFIX,
    RENT_SERIES_PREFIX,
    SP500_SERIES_ID,
    series_suffix,
)


class SimpleLocationModelParams(ApiModel):
    """Per-location annual adjustment layered on top of the simple base paths.

    The simple model first samples one home-value path and one rent path, then
    adjusts each requested location by `(1 + adj/100)^(months/12)`. Zero means
    the location rides the unadjusted base path.
    """

    home_value_annual_adjustment_pct: float = 0.0
    rent_annual_adjustment_pct: float = 0.0


class SimpleMarketModelConfig(ApiModel):
    """Deployment-supplied parameters for `SimpleJointMarketModel`."""

    location_params: dict[str, SimpleLocationModelParams] = Field(default_factory=dict)


class SimpleJointMarketModel(ApiModel):
    """Small stochastic joint model used until calibrated models plug in."""

    current_private_equity_price_usd: float = Field(default=0.0, ge=0.0)
    parameters: SimpleMarketModelConfig = Field(default_factory=SimpleMarketModelConfig)

    def sample(self, request: MarketSamplingRequest) -> SampledMarketBundle:
        rng = np.random.default_rng(request.seed)
        horizon_months = request.horizon_months
        rollout_count = request.rollout_count
        inflation = _lognormal_level_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=3.0,
            annual_volatility_pct=1.5,
        )
        sp500 = _lognormal_level_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=7.0,
            annual_volatility_pct=16.0,
        )
        private_equity_value = _lognormal_level_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=8.0,
            annual_volatility_pct=35.0,
        )
        home_base = _lognormal_level_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=3.5,
            annual_volatility_pct=8.0,
        )
        rent_base = _lognormal_level_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=3.0,
            annual_volatility_pct=3.0,
        )
        private_equity_events = np.zeros((rollout_count, horizon_months + 1), dtype=np.bool_)
        if horizon_months >= 12:
            event_draws = rng.random((rollout_count, horizon_months))
            private_equity_events[:, 1:] = event_draws < (1 / 72)

        level_blocks = [
            market_levels_frame(
                series_id,
                self._sample_level_series(
                    series_id,
                    inflation=inflation,
                    sp500=sp500,
                    private_equity_value=private_equity_value,
                    home_base=home_base,
                    rent_base=rent_base,
                ),
                rollout_count=rollout_count,
                horizon_months=horizon_months,
            )
            for series_id in sorted(request.required_level_series)
        ]
        event_blocks = [
            market_events_frame(
                event_id,
                self._sample_event_series(event_id, private_equity_events=private_equity_events),
                rollout_count=rollout_count,
                horizon_months=horizon_months,
            )
            for event_id in sorted(request.required_event_series)
        ]
        return SampledMarketBundle(
            levels=concat_frames(level_blocks, MARKET_LEVELS_SCHEMA),
            events=concat_frames(event_blocks, MARKET_EVENTS_SCHEMA),
            metadata={
                "market_model_id": "simple_joint_market_model",
                "current_private_equity_price_usd": self.current_private_equity_price_usd,
            },
        )

    def _sample_level_series(
        self,
        series_id: str,
        *,
        inflation: np.ndarray,
        sp500: np.ndarray,
        private_equity_value: np.ndarray,
        home_base: np.ndarray,
        rent_base: np.ndarray,
    ) -> np.ndarray:
        if series_id == INFLATION_SERIES_ID:
            return inflation
        if series_id == SP500_SERIES_ID:
            return sp500
        if location_id := series_suffix(series_id, HOME_VALUE_SERIES_PREFIX):
            return _location_level_path(
                home_base,
                annual_adjustment_pct=self.parameters.location_params.get(
                    location_id, SimpleLocationModelParams()
                ).home_value_annual_adjustment_pct,
            )
        if location_id := series_suffix(series_id, RENT_SERIES_PREFIX):
            return _location_level_path(
                rent_base,
                annual_adjustment_pct=self.parameters.location_params.get(
                    location_id, SimpleLocationModelParams()
                ).rent_annual_adjustment_pct,
            )
        if series_suffix(series_id, PRIVATE_EQUITY_SERIES_PREFIX) is not None:
            base_price = self.current_private_equity_price_usd or 1.0
            return base_price * private_equity_value
        if series_suffix(series_id, CRYPTO_SERIES_PREFIX) is not None:
            return np.ones_like(inflation)
        raise ValueError(f"simple market model cannot sample level series {series_id!r}")

    def _sample_event_series(self, event_id: str, *, private_equity_events: np.ndarray) -> np.ndarray:
        if series_suffix(event_id, PRIVATE_EQUITY_SALE_EVENT_PREFIX) is not None:
            return private_equity_events
        raise ValueError(f"simple market model cannot sample event series {event_id!r}")


def _lognormal_level_paths(
    rng: np.random.Generator,
    *,
    rollout_count: int,
    horizon_months: int,
    annual_return_pct: float,
    annual_volatility_pct: float,
) -> np.ndarray:
    monthly_sigma = annual_volatility_pct / 100 / np.sqrt(12)
    monthly_mu = annual_return_pct / 100 / 12 - 0.5 * monthly_sigma**2
    log_returns = rng.normal(monthly_mu, monthly_sigma, size=(rollout_count, horizon_months))
    paths = np.ones((rollout_count, horizon_months + 1), dtype="float64")
    if horizon_months > 0:
        paths[:, 1:] = np.exp(np.cumsum(log_returns, axis=1))
    return paths


def _location_level_path(base: np.ndarray, *, annual_adjustment_pct: float) -> np.ndarray:
    if annual_adjustment_pct == 0.0:
        return base
    horizon_months = base.shape[1] - 1
    months = np.arange(horizon_months + 1, dtype="float64")
    adjustment = (1 + annual_adjustment_pct / 100) ** (months / 12)
    return base * adjustment[None, :]
