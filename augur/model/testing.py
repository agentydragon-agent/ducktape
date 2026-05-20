"""Test-only sim-native market model fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from augur.core.market_bundle import MarketBundleProvider
from augur.frames import concat_frames
from augur.model.core_market_adapter import CoreMarketBundleProviderShim
from augur.model.sim_market import IndependentMarketModels
from augur.model.sim_market_api import (
    MARKET_EVENTS_SCHEMA,
    MarketSamplingRequest,
    SampledMarketBundle,
    market_events_frame,
)
from augur.model.sim_market_deterministic import Constant


def _fixture_metadata() -> dict[str, object]:
    return {
        "market_model_id": "deterministic_market_fixture",
        "market_model_version_id": "deterministic_market_fixture:v1",
        "scenario_generator_id": "deterministic_market_fixture",
        "scenario_generator_version_id": "deterministic_market_fixture:v1",
        "evidence_set_id": "fixture:deterministic",
        "calibration_artifact_id": "fixture:deterministic",
        "notes": ("deterministic sim-native market fixture",),
    }


@dataclass(frozen=True)
class DeterministicMarketFixtureModel:
    """Joint model fixture composed from constant scalar market models."""

    default_level_value: float = 1.0
    level_values: Mapping[str, float] = field(default_factory=dict)
    event_active_months: tuple[int, ...] = (12,)
    metadata: Mapping[str, object] = field(default_factory=_fixture_metadata)

    def sample(self, request: MarketSamplingRequest) -> SampledMarketBundle:
        level_models = IndependentMarketModels(
            markets={
                series_id: Constant(value=self.level_values.get(series_id, self.default_level_value))
                for series_id in sorted(request.required_level_series)
            }
        )
        event_blocks = [
            market_events_frame(
                event_id,
                self._event_mask(request),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for event_id in sorted(request.required_event_series)
        ]
        return SampledMarketBundle(
            levels=level_models.sample(request).levels,
            events=concat_frames(event_blocks, MARKET_EVENTS_SCHEMA),
            metadata=dict(self.metadata),
        )

    def _event_mask(self, request: MarketSamplingRequest) -> np.ndarray:
        active = np.zeros((request.rollout_count, request.horizon_months + 1), dtype=np.bool_)
        for month in self.event_active_months:
            if 0 <= month <= request.horizon_months:
                active[:, month] = True
        return active


def deterministic_market_provider(
    *,
    current_private_equity_price_usd: float = 0.0,
    default_level_value: float = 1.0,
    level_values: Mapping[str, float] | None = None,
    event_active_months: tuple[int, ...] = (12,),
) -> MarketBundleProvider:
    """Expose the deterministic sim fixture through the legacy core provider API."""

    return CoreMarketBundleProviderShim(
        model=DeterministicMarketFixtureModel(
            default_level_value=default_level_value,
            level_values={} if level_values is None else dict(level_values),
            event_active_months=event_active_months,
        ),
        current_private_equity_price_usd=current_private_equity_price_usd,
        scenario_generator_id="deterministic_market_fixture",
        scenario_generator_version_id="deterministic_market_fixture:v1",
        evidence_set_id="fixture:deterministic",
        calibration_artifact_id="fixture:deterministic",
        notes=("deterministic sim-native market fixture adapted to core MarketBundle",),
    )
