from __future__ import annotations

import numpy as np
import polars as pl
import pytest
import pytest_bazel

from augur.model.deterministic import Constant, Deterministic
from augur.model.exogenous import (
    SERIES_EVENTS_SCHEMA,
    SERIES_LEVELS_SCHEMA,
    SERIES_VALUES_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    series_events_frame,
    series_levels_frame,
    validate_sample_satisfies_request,
)
from augur.model.gbm import GeometricBrownian
from augur.model.series_model import IndependentSeriesModels, SeriesModelBundle, materialize_series_values
from augur.model.testing import DeterministicSeriesFixtureModel


def test_scalar_models_are_owned_by_model_modules() -> None:
    assert Deterministic.__module__ == "augur.model.deterministic"
    assert Constant.__module__ == "augur.model.deterministic"
    assert GeometricBrownian.__module__ == "augur.model.gbm"


def test_sampling_request_requires_explicit_rollout_seeds() -> None:
    with pytest.raises(TypeError):
        ExogenousSamplingRequest(horizon_months=2)  # type: ignore[call-arg]

    request = ExogenousSamplingRequest(horizon_months=2, rollout_seeds=[101, 102])  # type: ignore[arg-type]
    assert request.rollout_seeds == (101, 102)
    assert request.rollout_count == 2


def test_independent_model_samples_deterministic_levels_for_each_rollout() -> None:
    model = IndependentSeriesModels(series={"vti": Deterministic(levels=[100.0, 110.0, 120.0])})

    frame = model.sample(ExogenousSamplingRequest(horizon_months=2, rollout_seeds=(101, 102))).levels.sort(
        ["rollout_index", "month_index"]
    )

    assert frame.schema == SERIES_LEVELS_SCHEMA
    assert frame.to_dicts() == [
        {"rollout_index": 0, "month_index": 0, "series_id": "vti", "value": 100.0},
        {"rollout_index": 0, "month_index": 1, "series_id": "vti", "value": 110.0},
        {"rollout_index": 0, "month_index": 2, "series_id": "vti", "value": 120.0},
        {"rollout_index": 1, "month_index": 0, "series_id": "vti", "value": 100.0},
        {"rollout_index": 1, "month_index": 1, "series_id": "vti", "value": 110.0},
        {"rollout_index": 1, "month_index": 2, "series_id": "vti", "value": 120.0},
    ]


def test_bundle_api_unites_deterministic_constant_and_gbm_models() -> None:
    bundle = SeriesModelBundle.model_validate(
        {
            "model": {
                "kind": "independent",
                "series": {
                    "vti": {"kind": "deterministic", "levels": [100.0, 100.0, 100.0]},
                    "bnd": {"kind": "constant", "value": 95.0},
                    "qqq": {
                        "kind": "gbm",
                        "initial_value": 200.0,
                        "monthly_log_return_mu": 0.01,
                        "monthly_log_return_sigma": 0.02,
                    },
                },
            }
        }
    )

    first = materialize_series_values(bundle, rollout_seeds=(11, 12, 13), horizon_months=2)
    second = materialize_series_values(bundle, rollout_seeds=(11, 12, 13), horizon_months=2)

    assert first.schema == SERIES_VALUES_SCHEMA
    assert first.height == 27
    assert first.equals(second)
    assert first.filter((pl.col("series_id") == "qqq") & (pl.col("month_index") == 0))["value"].to_list() == [
        200.0,
        200.0,
        200.0,
    ]
    assert first.filter(pl.col("series_id") == "bnd")["value"].to_list() == [95.0] * 9


def test_deterministic_model_rejects_wrong_horizon_length() -> None:
    model = IndependentSeriesModels(series={"vti": Deterministic(levels=[100.0, 110.0])})

    with pytest.raises(ValueError, match=r"need 3"):
        model.sample(ExogenousSamplingRequest(horizon_months=2, rollout_seeds=(1,)))


def test_deterministic_fixture_samples_requested_constant_series_and_events() -> None:
    model = DeterministicSeriesFixtureModel(
        default_level_value=1.0, level_values={"sp500": 2.0}, event_active_months=(1,)
    )

    sampled = model.sample(
        ExogenousSamplingRequest(
            horizon_months=2,
            rollout_seeds=(101, 102),
            required_level_series=frozenset({"inflation", "sp500"}),
            required_event_series=frozenset({"private_equity_sale_opportunity:private_company_a"}),
        )
    )

    assert sampled.events.schema == SERIES_EVENTS_SCHEMA
    assert sampled.level_matrix("inflation", rollout_count=2, horizon_months=2).tolist() == [
        [1.0, 1.0, 1.0],
        [1.0, 1.0, 1.0],
    ]
    assert sampled.level_matrix("sp500", rollout_count=2, horizon_months=2).tolist() == [
        [2.0, 2.0, 2.0],
        [2.0, 2.0, 2.0],
    ]
    assert sampled.event_matrix(
        "private_equity_sale_opportunity:private_company_a", rollout_count=2, horizon_months=2
    ).tolist() == [[False, True, False], [False, True, False]]


def test_sample_compatibility_accepts_required_subset_and_extra_series() -> None:
    request = ExogenousSamplingRequest(
        horizon_months=2,
        rollout_seeds=(101,),
        required_level_series=frozenset({"sp500"}),
        required_event_series=frozenset({"private_equity_sale_opportunity:private_company_a"}),
    )
    sampled = SampledExogenousBundle(
        levels=pl.concat(
            [
                series_levels_frame("sp500", np.ones((1, 3)), rollout_count=1, horizon_months=2),
                series_levels_frame("extra_level", np.ones((1, 3)), rollout_count=1, horizon_months=2),
            ]
        ),
        events=pl.concat(
            [
                series_events_frame(
                    "private_equity_sale_opportunity:private_company_a",
                    np.zeros((1, 3), dtype=np.bool_),
                    rollout_count=1,
                    horizon_months=2,
                ),
                series_events_frame("extra_event", np.zeros((1, 3), dtype=np.bool_), rollout_count=1, horizon_months=2),
            ]
        ),
    )

    validate_sample_satisfies_request(request, sampled)


def test_sample_compatibility_rejects_missing_required_level_and_event_series() -> None:
    request = ExogenousSamplingRequest(
        horizon_months=2,
        rollout_seeds=(101,),
        required_level_series=frozenset({"prices_of_tea:china"}),
        required_event_series=frozenset({"event:tea_shock"}),
    )
    sampled = SampledExogenousBundle(levels=SERIES_LEVELS_SCHEMA.to_frame(), events=SERIES_EVENTS_SCHEMA.to_frame())

    with pytest.raises(ValueError, match="missing required level series") as exc_info:
        validate_sample_satisfies_request(request, sampled)

    assert "missing required level series: ['prices_of_tea:china']" in str(exc_info.value)
    assert "missing required event series: ['event:tea_shock']" in str(exc_info.value)


if __name__ == "__main__":
    pytest_bazel.main()
