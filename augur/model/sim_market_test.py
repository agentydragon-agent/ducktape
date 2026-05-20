from __future__ import annotations

import polars as pl
import pytest
import pytest_bazel

from augur.model.sim_market import IndependentMarketModels, MarketBundle, materialize_market_prices
from augur.model.sim_market_api import MARKET_PRICES_SCHEMA
from augur.model.sim_market_deterministic import Constant, Deterministic
from augur.model.sim_market_gbm import GeometricBrownian


def test_scalar_models_are_owned_by_model_modules() -> None:
    assert Deterministic.__module__ == "augur.model.sim_market_deterministic"
    assert Constant.__module__ == "augur.model.sim_market_deterministic"
    assert GeometricBrownian.__module__ == "augur.model.sim_market_gbm"


def test_independent_model_materializes_deterministic_prices_for_each_rollout() -> None:
    model = IndependentMarketModels(markets={"vti": Deterministic(prices_usd=[100.0, 110.0, 120.0])})

    frame = model.materialize(rollout_count=2, horizon_months=2).sort(["rollout_index", "month_index"])

    assert frame.schema == MARKET_PRICES_SCHEMA
    assert frame.to_dicts() == [
        {"rollout_index": 0, "month_index": 0, "asset_id": "vti", "price_per_unit_usd": 100.0},
        {"rollout_index": 0, "month_index": 1, "asset_id": "vti", "price_per_unit_usd": 110.0},
        {"rollout_index": 0, "month_index": 2, "asset_id": "vti", "price_per_unit_usd": 120.0},
        {"rollout_index": 1, "month_index": 0, "asset_id": "vti", "price_per_unit_usd": 100.0},
        {"rollout_index": 1, "month_index": 1, "asset_id": "vti", "price_per_unit_usd": 110.0},
        {"rollout_index": 1, "month_index": 2, "asset_id": "vti", "price_per_unit_usd": 120.0},
    ]


def test_bundle_api_unites_deterministic_constant_and_gbm_models() -> None:
    bundle = MarketBundle.model_validate(
        {
            "model": {
                "kind": "independent",
                "markets": {
                    "vti": {"kind": "deterministic", "prices_usd": [100.0, 100.0, 100.0]},
                    "bnd": {"kind": "constant", "price_usd": 95.0},
                    "qqq": {
                        "kind": "gbm",
                        "initial_price_usd": 200.0,
                        "monthly_log_return_mu": 0.01,
                        "monthly_log_return_sigma": 0.02,
                        "rng_seed": 11,
                    },
                },
            }
        }
    )

    first = materialize_market_prices(bundle, rollout_count=3, horizon_months=2)
    second = materialize_market_prices(bundle, rollout_count=3, horizon_months=2)

    assert first.schema == MARKET_PRICES_SCHEMA
    assert first.height == 27
    assert first.equals(second)
    assert first.filter((pl.col("asset_id") == "qqq") & (pl.col("month_index") == 0))[
        "price_per_unit_usd"
    ].to_list() == [200.0, 200.0, 200.0]
    assert first.filter(pl.col("asset_id") == "bnd")["price_per_unit_usd"].to_list() == [95.0] * 9


def test_deterministic_model_rejects_wrong_horizon_length() -> None:
    model = IndependentMarketModels(markets={"vti": Deterministic(prices_usd=[100.0, 110.0])})

    with pytest.raises(ValueError, match=r"need 3"):
        model.materialize(rollout_count=1, horizon_months=2)


if __name__ == "__main__":
    pytest_bazel.main()
