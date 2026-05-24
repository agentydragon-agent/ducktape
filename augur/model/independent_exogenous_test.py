from __future__ import annotations

import numpy as np
import pytest_bazel
from pydantic import TypeAdapter

from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.exogenous_provider_config import ExogenousProviderConfig
from augur.model.independent_exogenous import IndependentExogenousProviderConfig
from augur.model.series import (
    INFLATION_SERIES_ID,
    SP500_SERIES_ID,
    home_value_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
    rent_series_id,
)


def _example_config() -> IndependentExogenousProviderConfig:
    return IndependentExogenousProviderConfig.model_validate(
        {
            "type": "independent",
            "series": {
                INFLATION_SERIES_ID: {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0024906250,
                    "monthly_log_return_sigma": 0.0043301270,
                },
                SP500_SERIES_ID: {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0047333327,
                    "monthly_log_return_sigma": 0.0461880215,
                },
                home_value_series_id("san_francisco_ca"): {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0026498025,
                    "monthly_log_return_sigma": 0.0230940108,
                },
                rent_series_id("san_francisco_ca"): {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0024625000,
                    "monthly_log_return_sigma": 0.0086602540,
                },
                private_equity_series_id("private_equity_x"): {
                    "kind": "gbm",
                    "initial_value": 50.0,
                    "monthly_log_return_mu": 0.0015629326,
                    "monthly_log_return_sigma": 0.1010362971,
                },
            },
            "events": {
                private_equity_sale_event_id("private_equity_x"): {
                    "kind": "poisson",
                    "monthly_lambda": 0.0138888889,
                    "min_horizon_months": 12,
                }
            },
        }
    )


def test_independent_model_samples_levels_and_events() -> None:
    model = _example_config().realize_model()

    sampled = model.sample(
        ExogenousSamplingRequest(
            horizon_months=12,
            rollout_seeds=(7, 8),
            required_level_series=frozenset(
                {
                    INFLATION_SERIES_ID,
                    SP500_SERIES_ID,
                    home_value_series_id("san_francisco_ca"),
                    rent_series_id("san_francisco_ca"),
                    private_equity_series_id("private_equity_x"),
                }
            ),
            required_event_series=frozenset({private_equity_sale_event_id("private_equity_x")}),
        )
    )

    assert set(sampled.levels.get_column("series_id").unique()) == {
        INFLATION_SERIES_ID,
        SP500_SERIES_ID,
        home_value_series_id("san_francisco_ca"),
        rent_series_id("san_francisco_ca"),
        private_equity_series_id("private_equity_x"),
    }
    assert sampled.level_matrix(private_equity_series_id("private_equity_x"), rollout_count=2, horizon_months=12)[
        :, 0
    ].tolist() == [50.0, 50.0]
    assert (
        sampled.event_matrix(private_equity_sale_event_id("private_equity_x"), rollout_count=2, horizon_months=12).dtype
        == np.bool_
    )
    assert sampled.metadata["exogenous_model_id"] == "independent_exogenous_model"
    assert sampled.metadata["private_equity_prices_usd"] == {"private_equity_x": 50.0}


def test_independent_provider_config_roundtrips_through_discriminated_union() -> None:
    adapter: TypeAdapter[ExogenousProviderConfig] = TypeAdapter(ExogenousProviderConfig)
    config = adapter.validate_python(_example_config().model_dump())
    assert isinstance(config, IndependentExogenousProviderConfig)
    assert config.realize_model().sample(ExogenousSamplingRequest(horizon_months=3, rollout_seeds=(9,))).metadata[
        "private_equity_prices_usd"
    ] == {"private_equity_x": 50.0}


if __name__ == "__main__":
    pytest_bazel.main()
