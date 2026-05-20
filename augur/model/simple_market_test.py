from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.model.market_api import MarketSamplingRequest
from augur.model.market_provider_config import SimpleMarketProviderConfig
from augur.model.series import (
    INFLATION_SERIES_ID,
    SP500_SERIES_ID,
    crypto_series_id,
    home_value_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
    rent_series_id,
)
from augur.model.simple_market import SimpleLocationModelParams, SimpleMarketModel, SimpleMarketModelConfig


def test_simple_model_samples_levels_and_events() -> None:
    model = SimpleMarketModel(
        current_private_equity_price_usd=50.0,
        parameters=SimpleMarketModelConfig(
            location_params={"san_francisco_ca": SimpleLocationModelParams(home_value_annual_adjustment_pct=12.0)}
        ),
    )

    sampled = model.sample(
        MarketSamplingRequest(
            horizon_months=12,
            rollout_seeds=(7, 8),
            required_level_series=frozenset(
                {
                    INFLATION_SERIES_ID,
                    SP500_SERIES_ID,
                    home_value_series_id("san_francisco_ca"),
                    rent_series_id("san_francisco_ca"),
                    private_equity_series_id("openai"),
                    crypto_series_id("BTC"),
                }
            ),
            required_event_series=frozenset({private_equity_sale_event_id("openai")}),
        )
    )

    assert set(sampled.levels.get_column("series_id").unique()) == {
        INFLATION_SERIES_ID,
        SP500_SERIES_ID,
        home_value_series_id("san_francisco_ca"),
        rent_series_id("san_francisco_ca"),
        private_equity_series_id("openai"),
        crypto_series_id("BTC"),
    }
    assert sampled.level_matrix(private_equity_series_id("openai"), rollout_count=2, horizon_months=12)[
        :, 0
    ].tolist() == [50.0, 50.0]
    assert (
        sampled.event_matrix(private_equity_sale_event_id("openai"), rollout_count=2, horizon_months=12).dtype
        == np.bool_
    )


def test_simple_provider_config_realizes_native_model() -> None:
    config = SimpleMarketProviderConfig(
        location_params={"san_francisco_ca": SimpleLocationModelParams(rent_annual_adjustment_pct=2.0)}
    )
    model = config.realize_model(current_private_equity_price_usd=50.0)
    sampled = model.sample(
        MarketSamplingRequest(
            horizon_months=3, rollout_seeds=(9,), required_level_series=frozenset({rent_series_id("san_francisco_ca")})
        )
    )

    assert isinstance(model, SimpleMarketModel)
    assert sampled.metadata["market_model_id"] == "simple_market_model"
    assert sampled.level_matrix(rent_series_id("san_francisco_ca"), rollout_count=1, horizon_months=3)[0, 0] == 1.0


if __name__ == "__main__":
    pytest_bazel.main()
