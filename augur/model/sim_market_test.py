from __future__ import annotations

import polars as pl
import pytest
import pytest_bazel

from augur.model.sim_market import IndependentMarketModels, MarketBundle, materialize_market_prices
from augur.model.sim_market_api import MARKET_LEVELS_SCHEMA, MARKET_PRICES_SCHEMA, MarketSamplingRequest
from augur.model.sim_market_deterministic import Constant, Deterministic
from augur.model.sim_market_gbm import GeometricBrownian


def test_scalar_models_are_owned_by_model_modules() -> None:
    assert Deterministic.__module__ == "augur.model.sim_market_deterministic"
    assert Constant.__module__ == "augur.model.sim_market_deterministic"
    assert GeometricBrownian.__module__ == "augur.model.sim_market_gbm"


def test_sampling_request_requires_explicit_rollout_seeds() -> None:
    with pytest.raises(TypeError):
        MarketSamplingRequest(horizon_months=2)  # type: ignore[call-arg]

    request = MarketSamplingRequest(horizon_months=2, rollout_seeds=[101, 102])  # type: ignore[arg-type]
    assert request.rollout_seeds == (101, 102)
    assert request.rollout_count == 2


def test_independent_model_samples_deterministic_levels_for_each_rollout() -> None:
    model = IndependentMarketModels(markets={"vti": Deterministic(levels=[100.0, 110.0, 120.0])})

    frame = model.sample(MarketSamplingRequest(horizon_months=2, rollout_seeds=(101, 102))).levels.sort(
        ["rollout_index", "month_index"]
    )

    assert frame.schema == MARKET_LEVELS_SCHEMA
    assert frame.to_dicts() == [
        {"rollout_index": 0, "month_index": 0, "series_id": "vti", "value": 100.0},
        {"rollout_index": 0, "month_index": 1, "series_id": "vti", "value": 110.0},
        {"rollout_index": 0, "month_index": 2, "series_id": "vti", "value": 120.0},
        {"rollout_index": 1, "month_index": 0, "series_id": "vti", "value": 100.0},
        {"rollout_index": 1, "month_index": 1, "series_id": "vti", "value": 110.0},
        {"rollout_index": 1, "month_index": 2, "series_id": "vti", "value": 120.0},
    ]


def test_bundle_api_unites_deterministic_constant_and_gbm_models() -> None:
    bundle = MarketBundle.model_validate(
        {
            "model": {
                "kind": "independent",
                "markets": {
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

    first = materialize_market_prices(bundle, rollout_seeds=(11, 12, 13), horizon_months=2)
    second = materialize_market_prices(bundle, rollout_seeds=(11, 12, 13), horizon_months=2)

    assert first.schema == MARKET_PRICES_SCHEMA
    assert first.height == 27
    assert first.equals(second)
    assert first.filter((pl.col("asset_id") == "qqq") & (pl.col("month_index") == 0))[
        "price_per_unit_usd"
    ].to_list() == [200.0, 200.0, 200.0]
    assert first.filter(pl.col("asset_id") == "bnd")["price_per_unit_usd"].to_list() == [95.0] * 9


def test_deterministic_model_rejects_wrong_horizon_length() -> None:
    model = IndependentMarketModels(markets={"vti": Deterministic(levels=[100.0, 110.0])})

    with pytest.raises(ValueError, match=r"need 3"):
        model.sample(MarketSamplingRequest(horizon_months=2, rollout_seeds=(1,)))


if __name__ == "__main__":
    pytest_bazel.main()
