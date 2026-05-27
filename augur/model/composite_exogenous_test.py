from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
import pytest_bazel

from augur.frames import concat_frames
from augur.model.composite_exogenous import CompositeExogenousModel
from augur.model.exogenous import (
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_events_frame,
    series_levels_frame,
)
from augur.model.series import INFLATION_SERIES_ID, private_equity_sale_event_id, private_equity_series_id


@dataclass(frozen=True)
class _StaticSampler:
    levels: dict[str, float]
    events: dict[str, int]

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        level_frames = [
            series_levels_frame(
                series_id,
                np.full((request.rollout_count, request.horizon_months + 1), value, dtype=np.float64),
                rollout_count=request.rollout_count,
                horizon_months=request.horizon_months,
            )
            for series_id, value in self.levels.items()
        ]
        event_frames = []
        for event_id, month in self.events.items():
            active = np.zeros((request.rollout_count, request.horizon_months + 1), dtype=np.bool_)
            if month <= request.horizon_months:
                active[:, month] = True
            event_frames.append(
                series_events_frame(
                    event_id, active, rollout_count=request.rollout_count, horizon_months=request.horizon_months
                )
            )
        return SampledExogenousBundle(
            levels=concat_frames(level_frames, SERIES_LEVELS_SCHEMA),
            events=concat_frames(event_frames, SERIES_EVENTS_SCHEMA),
        )


def test_composite_merges_macro_and_private_equity_series() -> None:
    model = CompositeExogenousModel(
        macro=_StaticSampler(levels={INFLATION_SERIES_ID: 1.0}, events={}),
        private_equity=_StaticSampler(
            levels={private_equity_series_id("openai"): 687.69}, events={private_equity_sale_event_id("openai"): 2}
        ),
    )
    request = ExogenousSamplingRequest(
        horizon_months=3,
        rollout_seeds=(7,),
        required_level_series=frozenset({INFLATION_SERIES_ID, private_equity_series_id("openai")}),
        required_event_series=frozenset({private_equity_sale_event_id("openai")}),
    )

    bundle = model.sample(request)

    assert bundle.level_matrix(INFLATION_SERIES_ID, rollout_count=1, horizon_months=3)[0, 0] == 1.0
    assert bundle.level_matrix(private_equity_series_id("openai"), rollout_count=1, horizon_months=3)[0, 0] == 687.69
    assert bundle.event_matrix(private_equity_sale_event_id("openai"), rollout_count=1, horizon_months=3)[0, 2]


def test_composite_rejects_duplicate_series_outputs() -> None:
    model = CompositeExogenousModel(
        macro=_StaticSampler(levels={private_equity_series_id("openai"): 1.0}, events={}),
        private_equity=_StaticSampler(levels={private_equity_series_id("openai"): 2.0}, events={}),
    )

    with pytest.raises(ValueError, match="duplicate level series"):
        model.sample(
            ExogenousSamplingRequest(
                horizon_months=1,
                rollout_seeds=(1,),
                required_level_series=frozenset({private_equity_series_id("openai")}),
            )
        )


def test_composite_rejects_missing_required_private_equity_series() -> None:
    model = CompositeExogenousModel(
        macro=_StaticSampler(levels={INFLATION_SERIES_ID: 1.0}, events={}),
        private_equity=_StaticSampler(
            levels={private_equity_series_id("openai"): 687.69}, events={private_equity_sale_event_id("openai"): 1}
        ),
    )

    with pytest.raises(ValueError, match="missing required level series"):
        model.sample(
            ExogenousSamplingRequest(
                horizon_months=1,
                rollout_seeds=(1,),
                required_level_series=frozenset({private_equity_series_id("different_issuer")}),
            )
        )


if __name__ == "__main__":
    pytest_bazel.main()
