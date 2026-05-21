"""Test-only exogenous path model fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from augur.frames import concat_frames
from augur.model.deterministic import Constant
from augur.model.exogenous import (
    SERIES_EVENTS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_events_frame,
)
from augur.model.series_model import IndependentSeriesModels


def _fixture_metadata() -> dict[str, object]:
    return {
        "exogenous_model_id": "deterministic_series_fixture",
        "exogenous_model_version_id": "deterministic_series_fixture:v1",
        "scenario_generator_id": "deterministic_series_fixture",
        "scenario_generator_version_id": "deterministic_series_fixture:v1",
        "evidence_set_id": "fixture:deterministic",
        "calibration_artifact_id": "fixture:deterministic",
        "notes": ("deterministic series fixture",),
    }


@dataclass(frozen=True)
class DeterministicSeriesFixtureModel:
    """Joint model fixture composed from constant scalar series models."""

    default_level_value: float = 1.0
    level_values: Mapping[str, float] = field(default_factory=dict)
    event_active_months: tuple[int, ...] = (12,)
    metadata: Mapping[str, object] = field(default_factory=_fixture_metadata)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        level_models = IndependentSeriesModels(
            series={
                series_id: Constant(value=self.level_values.get(series_id, self.default_level_value))
                for series_id in sorted(request.required_level_series)
            }
        )
        event_blocks = [
            series_events_frame(
                event_id,
                self._event_mask(request),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for event_id in sorted(request.required_event_series)
        ]
        return SampledExogenousBundle(
            levels=level_models.sample(request).levels,
            events=concat_frames(event_blocks, SERIES_EVENTS_SCHEMA),
            metadata=dict(self.metadata),
        )

    def _event_mask(self, request: ExogenousSamplingRequest) -> np.ndarray:
        active = np.zeros((request.rollout_count, request.horizon_months + 1), dtype=np.bool_)
        for month in self.event_active_months:
            if 0 <= month <= request.horizon_months:
                active[:, month] = True
        return active
