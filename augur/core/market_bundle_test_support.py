from __future__ import annotations

import numpy as np

from augur.core.local_regulation import LocationId
from augur.core.market_bundle import MarketBundle, MarketBundleMetadata


def constant_market_bundle(
    *,
    rollout_count: int = 2,
    horizon_months: int = 3,
    inflation_path: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0),
    home_path: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0),
    rent_path: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0),
) -> MarketBundle:
    shape = (rollout_count, horizon_months + 1)
    month_index = np.arange(horizon_months + 1, dtype="int64")

    def multiplier(values: tuple[float, ...]) -> np.ndarray:
        source = np.asarray(values, dtype="float64")
        if source.size < horizon_months + 1:
            source = np.pad(source, (0, horizon_months + 1 - source.size), constant_values=source[-1])
        return np.broadcast_to(source[: horizon_months + 1], shape).copy()

    ones = np.ones(shape, dtype="float64")
    zeros = np.zeros(shape, dtype="float64")
    home = multiplier(home_path)
    rent = multiplier(rent_path)
    return MarketBundle(
        month_index=month_index,
        inflation_multipliers=multiplier(inflation_path),
        generic_sp500_multipliers=ones,
        home_value_multipliers_by_location={
            "default": home,
            LocationId.SAN_FRANCISCO_CA.value: home,
            LocationId.VALLEJO_CA.value: home,
            LocationId.MARE_ISLAND_VALLEJO_CA.value: home,
        },
        rent_multipliers_by_location={
            "default": rent,
            LocationId.SAN_FRANCISCO_CA.value: rent,
            LocationId.VALLEJO_CA.value: rent,
            LocationId.MARE_ISLAND_VALLEJO_CA.value: rent,
        },
        mortgage_30y_rate_pct=zeros,
        private_equity_value_multipliers=ones,
        private_equity_liquidity_event_mask=np.zeros(shape, dtype=np.bool_),
        private_equity_tender_sale_fraction=zeros,
        metadata=MarketBundleMetadata(
            market_model_id="test",
            random_seed=None,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            factor_ids=(),
            event_stream_ids=(),
        ),
    )
