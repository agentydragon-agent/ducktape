from __future__ import annotations

import numpy as np
import pytest
import pytest_bazel

from augur.core.market_bundle import MarketBundle, MarketBundleMetadata, SimpleMarketBundleProvider
from augur.core.scenario_set import MarketRequest


def test_simple_market_bundle_shapes_and_reproducibility() -> None:
    request = MarketRequest(market_model_id="simple_test", rollout_count=4, horizon_months=18, random_seed=123)
    provider = SimpleMarketBundleProvider()

    first = provider.sample_market_bundle(
        rollout_count=request.rollout_count,
        horizon_months=request.horizon_months,
        seed=request.random_seed,
        market_request=request,
    )
    second = provider.sample_market_bundle(
        rollout_count=request.rollout_count,
        horizon_months=request.horizon_months,
        seed=request.random_seed,
        market_request=request,
    )

    assert first.generic_sp500_multipliers.shape == (4, 19)
    assert first.private_equity_liquidity_event_mask.shape == (4, 19)
    assert first.private_equity_liquidity_event_mask.dtype == np.bool_
    np.testing.assert_array_equal(first.month_index, np.arange(19, dtype="int64"))
    np.testing.assert_allclose(first.generic_sp500_multipliers, second.generic_sp500_multipliers)
    np.testing.assert_allclose(first.inflation_multipliers[:, 0], 1.0)
    np.testing.assert_allclose(first.private_equity_value_multipliers[:, 0], 1.0)
    assert np.all(first.private_equity_tender_sale_fraction >= 0)
    assert np.all(first.private_equity_tender_sale_fraction <= 1)


def test_market_bundle_rejects_bad_shapes() -> None:
    metadata = MarketBundleMetadata(
        market_model_id="bad", random_seed=1, rollout_count=2, horizon_months=3, factor_ids=(), event_stream_ids=()
    )
    valid = np.ones((2, 4), dtype="float64")

    with pytest.raises(ValueError, match="generic_sp500_multipliers"):
        MarketBundle(
            month_index=np.arange(4, dtype="int64"),
            inflation_multipliers=valid,
            generic_sp500_multipliers=np.ones((2, 3), dtype="float64"),
            home_value_multipliers_by_location={"default": valid},
            rent_multipliers_by_location={"default": valid},
            mortgage_30y_rate_pct=np.full((2, 4), 6.5, dtype="float64"),
            private_equity_value_multipliers=valid,
            private_equity_liquidity_event_mask=np.zeros((2, 4), dtype=np.bool_),
            private_equity_tender_sale_fraction=np.zeros((2, 4), dtype="float64"),
            metadata=metadata,
        )


if __name__ == "__main__":
    pytest_bazel.main()
