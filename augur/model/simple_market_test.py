from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.core.market_bundle import RequiredMarketKeys
from augur.core.scenario_set import MarketRequest
from augur.model.core_market_adapter import CoreMarketBundleProviderShim
from augur.model.market_provider_config import SimpleMarketProviderConfig
from augur.model.sim_market_api import MarketSamplingRequest
from augur.model.sim_market_series import (
    INFLATION_SERIES_ID,
    SP500_SERIES_ID,
    crypto_series_id,
    home_value_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
    rent_series_id,
)
from augur.model.simple_market import SimpleJointMarketModel, SimpleLocationModelParams, SimpleMarketModelConfig


def test_simple_joint_model_samples_levels_and_events() -> None:
    model = SimpleJointMarketModel(
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


def test_core_adapter_normalizes_sim_levels_to_legacy_multipliers() -> None:
    provider = CoreMarketBundleProviderShim(
        model=SimpleJointMarketModel(current_private_equity_price_usd=50.0), current_private_equity_price_usd=50.0
    )

    bundle = provider.sample_market_bundle(
        rollout_count=2,
        horizon_months=12,
        seed=7,
        market_request=MarketRequest(market_model_id="simple", rollout_count=2, horizon_months=12, seed=7),
        required_keys=RequiredMarketKeys(
            location_ids=frozenset({"san_francisco_ca"}),
            pe_issuer_ids=frozenset({"openai"}),
            crypto_symbols=frozenset({"BTC"}),
        ),
    )

    assert np.allclose(bundle.inflation_multipliers[:, 0], 1.0)
    assert np.allclose(bundle.generic_sp500_multipliers[:, 0], 1.0)
    assert np.allclose(bundle.home_value_multipliers("san_francisco_ca")[:, 0], 1.0)
    assert np.allclose(bundle.rent_multipliers("san_francisco_ca")[:, 0], 1.0)
    assert np.allclose(bundle.private_equity_value_multiplier("openai")[:, 0], 1.0)
    assert np.allclose(bundle.crypto_value_multiplier("BTC"), 1.0)
    assert np.allclose(bundle.mortgage_30y_rate_pct, 6.5)
    assert bundle.private_equity_sale_opportunity_mask_for("openai").dtype == np.bool_
    assert bundle.metadata.current_private_equity_price_usd == 50.0
    assert bundle.metadata.source_metadata["market_model_id"] == "simple_joint_market_model"


def test_simple_provider_config_realizes_sim_native_model_behind_core_adapter() -> None:
    provider = SimpleMarketProviderConfig(
        location_params={"san_francisco_ca": SimpleLocationModelParams(rent_annual_adjustment_pct=2.0)}
    ).realize(current_private_equity_price_usd=50.0)

    bundle = provider.sample_market_bundle(
        rollout_count=1,
        horizon_months=3,
        seed=9,
        market_request=MarketRequest(market_model_id="simple", rollout_count=1, horizon_months=3, seed=9),
        required_keys=RequiredMarketKeys(location_ids=frozenset({"san_francisco_ca"})),
    )

    assert bundle.metadata.scenario_generator_id == "sim_market_bundle_provider_shim"
    assert np.allclose(bundle.rent_multipliers("san_francisco_ca")[:, 0], 1.0)


if __name__ == "__main__":
    pytest_bazel.main()
