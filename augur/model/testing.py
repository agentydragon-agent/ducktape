"""Test-only exogenous path model fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from augur.model.deterministic import Constant
from augur.model.exogenous import ExogenousSamplingRequest, SampledExogenousBundle
from augur.model.private_equity_bundle import PrivateEquityBundle
from augur.model.private_equity_protocol import neutral_private_equity_issuer_bundle
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
        tender_events = self._event_mask(request)
        # The default issuer mark for fixture scenarios is just the default
        # level value — the production anchoring step rescales it to whatever
        # `unit_value_usd` the portfolio config sets.
        default_mark = np.full(
            (request.rollout_count, request.horizon_months + 1), self.default_level_value, dtype=np.float64
        )
        pe_bundle_parts = [
            neutral_private_equity_issuer_bundle(
                issuer_id,
                observed_mark=default_mark,
                tender_events=tender_events,
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for issuer_id in sorted(request.required_private_equity_issuers)
        ]
        return SampledExogenousBundle(
            levels=level_models.sample(request).levels,
            private_equity=(
                PrivateEquityBundle.combine(pe_bundle_parts) if pe_bundle_parts else PrivateEquityBundle.empty()
            ),
            metadata=dict(self.metadata),
        )

    def _event_mask(self, request: ExogenousSamplingRequest) -> np.ndarray:
        active = np.zeros((request.rollout_count, request.horizon_months + 1), dtype=np.bool_)
        for month in self.event_active_months:
            if 0 <= month <= request.horizon_months:
                active[:, month] = True
        return active
