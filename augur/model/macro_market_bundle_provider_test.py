"""Shape-contract tests for the generic macro market-bundle provider.

`MacroMarketBundleProvider.from_loaded_model(...)` no longer reaches out to
source CSVs or fits a model — it composes a provider around a pre-fit model
plus the deployment-side calibration snapshot. The end-to-end "train offline,
load asset, sample" path is exercised by `:vecm_round_trip_test`.

These tests use a fake `_FixedScenariosModel` so the bundle's shape contract
is decoupled from any specific macro model's fit/sample internals.
"""

from __future__ import annotations

import numpy as np
import pytest
import pytest_bazel
from numpy.testing import assert_allclose

from augur.core.market_bundle import RequiredMarketKeys
from augur.core.scenario_set import MarketRequest
from augur.model.location_market_sources import LocationMarketSources
from augur.model.macro_market_bundle_provider import MacroMarketBundleProvider
from augur.model.markets.scenarios import HistoricalSeries, Scenarios

_FACTOR_NAMES: tuple[str, ...] = ("sp500", "home", "vallejo_home", "rent", "inflation")
_LOCATIONS = frozenset({"san_francisco_ca", "vallejo_ca", "mare_island_vallejo_ca"})


class _FixedScenariosModel:
    """Test fake — produces flat (all-ones) multiplier paths so the assembly
    layer is checked against a known-deterministic input."""

    label = "fixed_test_model"
    factor_names: tuple[str, ...] = _FACTOR_NAMES

    def fit(self, historical: HistoricalSeries) -> None:
        del historical

    def simulate(self, n_paths: int, n_months: int, seed: int) -> Scenarios:
        return Scenarios(
            factor_names=_FACTOR_NAMES,
            multipliers=np.ones((n_paths, n_months + 1, len(_FACTOR_NAMES))),
            seed=seed,
            label=self.label,
        )

    def log_predictive_density(self, historical: HistoricalSeries, t: int) -> float | None:
        del historical, t
        return None

    def log_predictive_marginals(self, historical: HistoricalSeries, t: int) -> dict[str, float] | None:
        del historical, t
        return None

    def log_predictive_density_at_horizon(self, historical: HistoricalSeries, t: int, h: int) -> float | None:
        del historical, t, h
        return None


def _provider() -> MacroMarketBundleProvider:
    return MacroMarketBundleProvider.from_loaded_model(
        _FixedScenariosModel(),
        latest_observations={"sp500": 5500.0, "home": 1.0, "vallejo_home": 1.0, "rent": 1.0, "inflation": 1.0},
        current_mortgage30_rate_pct=6.5,
        current_private_equity_price_usd=100.0,
        location_market_sources=LocationMarketSources(
            home_value={
                "san_francisco_ca": "home",
                "vallejo_ca": "vallejo_home",
                "mare_island_vallejo_ca": "vallejo_home",
            },
            rent={"san_francisco_ca": "rent", "vallejo_ca": "rent", "mare_island_vallejo_ca": "rent"},
        ),
        evidence_source_id="test-fixture",
    )


def _request() -> MarketRequest:
    return MarketRequest(market_model_id="fixed_test_model", rollout_count=3, horizon_months=24, seed=42)


def test_sample_market_bundle_shape() -> None:
    provider = _provider()
    bundle = provider.sample_market_bundle(
        rollout_count=3,
        horizon_months=24,
        seed=42,
        market_request=_request(),
        required_keys=RequiredMarketKeys(location_ids=_LOCATIONS),
    )

    expected_shape = (3, 25)
    assert bundle.rollout_count == 3
    assert bundle.horizon_months == 24
    assert bundle.metadata.seed == 42
    assert bundle.metadata.market_model_version_id.startswith("model_version:")
    assert bundle.metadata.evidence_set_id.startswith("evidence_set:")
    assert bundle.metadata.calibration_artifact_id.startswith("calibration_artifact:")
    assert bundle.metadata.risk_factor_set_id.startswith("risk_factor_set:")
    assert {"sp500", "rent", "inflation"} <= set(bundle.metadata.risk_factor_ids)
    assert bundle.metadata.current_private_equity_price_usd == 100.0
    assert bundle.metadata.source_metadata["market_provider_label"] == "fixed_test_model"
    np.testing.assert_array_equal(bundle.month_index, np.arange(25, dtype="int64"))
    for key in ("inflation_multipliers", "generic_sp500_multipliers", "mortgage_30y_rate_pct"):
        values = getattr(bundle, key)
        assert values.shape == expected_shape, key
    assert set(bundle.home_value_multipliers_by_location) == _LOCATIONS
    assert set(bundle.rent_multipliers_by_location) == _LOCATIONS


def test_mortgage_path_constant() -> None:
    bundle = _provider().sample_market_bundle(
        rollout_count=1,
        horizon_months=24,
        seed=42,
        market_request=_request(),
        required_keys=RequiredMarketKeys(location_ids=_LOCATIONS),
    )
    arr = bundle.mortgage_30y_rate_pct[0]
    assert_allclose(arr, 6.5)


def test_provider_populates_every_required_pe_issuer() -> None:
    bundle = _provider().sample_market_bundle(
        rollout_count=1,
        horizon_months=24,
        seed=42,
        market_request=_request(),
        required_keys=RequiredMarketKeys(location_ids=_LOCATIONS, pe_issuer_ids=frozenset({"issuer_a", "issuer_b"})),
    )
    assert set(bundle.private_equity_value_multipliers_by_issuer) == {"issuer_a", "issuer_b"}
    assert set(bundle.private_equity_sale_opportunity_mask_by_issuer) == {"issuer_a", "issuer_b"}


def test_provider_raises_on_missing_required_location() -> None:
    with pytest.raises(ValueError, match="missing_location"):
        _provider().sample_market_bundle(
            rollout_count=1,
            horizon_months=24,
            seed=42,
            market_request=_request(),
            required_keys=RequiredMarketKeys(location_ids=frozenset({"missing_location"})),
        )


if __name__ == "__main__":
    pytest_bazel.main()
