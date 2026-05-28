from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest
import pytest_bazel

from augur.frames import concat_frames
from augur.model.composite_exogenous import CompositeExogenousModel
from augur.model.exogenous import (
    PRIVATE_EQUITY_PROTOCOL_SCHEMA,
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_events_frame,
    series_levels_frame,
)
from augur.model.private_equity_protocol import neutral_private_equity_protocol_frame
from augur.model.series import (
    INFLATION_SERIES_ID,
    private_equity_eligible_fraction_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
)


@dataclass(frozen=True)
class _StaticSampler:
    levels: dict[str, float]
    events: dict[str, int]
    sample_requests: list[ExogenousSamplingRequest] = field(default_factory=list)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        self.sample_requests.append(request)
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
            private_equity_protocol=concat_frames(
                [
                    neutral_private_equity_protocol_frame(
                        issuer,
                        tender_events=np.zeros((request.rollout_count, request.horizon_months + 1), dtype=np.bool_),
                        rollout_count=request.rollout_count,
                        horizon_months=request.horizon_months,
                    )
                    for issuer in sorted(request.required_private_equity_protocol_issuers)
                ],
                PRIVATE_EQUITY_PROTOCOL_SCHEMA,
            ),
        )


def test_composite_merges_macro_and_private_equity_series() -> None:
    macro = _StaticSampler(levels={INFLATION_SERIES_ID: 1.0}, events={})
    private_equity = _StaticSampler(
        levels={
            private_equity_series_id("private_company_a"): 687.69,
            private_equity_eligible_fraction_series_id("private_company_a"): 0.5,
        },
        events={private_equity_sale_event_id("private_company_a"): 2},
    )
    model = CompositeExogenousModel(macro=macro, private_equity=private_equity)
    request = ExogenousSamplingRequest(
        horizon_months=3,
        rollout_seeds=(7,),
        required_level_series=frozenset(
            {
                INFLATION_SERIES_ID,
                private_equity_series_id("private_company_a"),
                private_equity_eligible_fraction_series_id("private_company_a"),
            }
        ),
        required_event_series=frozenset({private_equity_sale_event_id("private_company_a")}),
        required_private_equity_protocol_issuers=frozenset({"private_company_a"}),
    )

    bundle = model.sample(request)

    assert bundle.level_matrix(INFLATION_SERIES_ID, rollout_count=1, horizon_months=3)[0, 0] == 1.0
    assert (
        bundle.level_matrix(private_equity_series_id("private_company_a"), rollout_count=1, horizon_months=3)[0, 0]
        == 687.69
    )
    assert bundle.event_matrix(private_equity_sale_event_id("private_company_a"), rollout_count=1, horizon_months=3)[
        0, 2
    ]
    assert macro.sample_requests[0].required_level_series == frozenset({INFLATION_SERIES_ID})
    assert private_equity.sample_requests[0].required_level_series == frozenset(
        {private_equity_series_id("private_company_a"), private_equity_eligible_fraction_series_id("private_company_a")}
    )
    assert macro.sample_requests[0].required_private_equity_protocol_issuers == frozenset()
    assert private_equity.sample_requests[0].required_private_equity_protocol_issuers == frozenset(
        {"private_company_a"}
    )


def test_composite_rejects_duplicate_series_outputs() -> None:
    model = CompositeExogenousModel(
        macro=_StaticSampler(levels={private_equity_series_id("private_company_a"): 1.0}, events={}),
        private_equity=_StaticSampler(levels={private_equity_series_id("private_company_a"): 2.0}, events={}),
    )

    with pytest.raises(ValueError, match="duplicate level series"):
        model.sample(
            ExogenousSamplingRequest(
                horizon_months=1,
                rollout_seeds=(1,),
                required_level_series=frozenset({private_equity_series_id("private_company_a")}),
            )
        )


def test_composite_rejects_missing_required_private_equity_series() -> None:
    model = CompositeExogenousModel(
        macro=_StaticSampler(levels={INFLATION_SERIES_ID: 1.0}, events={}),
        private_equity=_StaticSampler(
            levels={private_equity_series_id("private_company_a"): 687.69},
            events={private_equity_sale_event_id("private_company_a"): 1},
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
