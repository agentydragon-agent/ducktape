"""Shape-contract tests for the generic macro market-bundle provider.

Parametrised across every label in the registry, so every shipped macro
model is shape-checked against the MarketBundle contract automatically.
The model-internal correctness tests live next to each model in
`markets/models/*_test.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import pytest_bazel
from numpy.testing import assert_allclose
from pydantic import ValidationError

from augur.core.scenario_set import MarketRequest
from augur.model.macro_market_bundle_provider import MacroMarketBundleProvider
from augur.model.markets.registry import LABELS

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "market_config.example.json"


@pytest.fixture(params=LABELS)
def provider(request: pytest.FixtureRequest) -> MacroMarketBundleProvider:
    return MacroMarketBundleProvider.for_label(
        request.param, config_path=CONFIG_PATH, current_private_equity_price_usd=100.0
    )


def test_metadata_populated(provider: MacroMarketBundleProvider) -> None:
    assert provider.label in LABELS
    assert isinstance(provider.latest_observations, dict)


def test_provider_rejects_unknown_market_config_fields(tmp_path: Path) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["unused_knob"] = True
    config_path = tmp_path / "market_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValidationError, match="unused_knob"):
        MacroMarketBundleProvider.for_label(LABELS[0], config_path=config_path, current_private_equity_price_usd=100.0)


def _request(provider: MacroMarketBundleProvider, *, rollout_count: int = 3, horizon_months: int = 24) -> MarketRequest:
    return MarketRequest(
        market_model_id=provider.label, rollout_count=rollout_count, horizon_months=horizon_months, seed=42
    )


def _sample(provider: MacroMarketBundleProvider, *, rollout_count: int = 3, horizon_months: int = 24):
    request = _request(provider, rollout_count=rollout_count, horizon_months=horizon_months)
    return provider.sample_market_bundle(
        rollout_count=rollout_count, horizon_months=horizon_months, seed=request.seed, market_request=request
    )


def test_sample_market_bundle_shape(provider: MacroMarketBundleProvider) -> None:
    n_rollouts = 3
    horizon_months = 24
    bundle = _sample(provider, rollout_count=n_rollouts, horizon_months=horizon_months)
    expected_shape = (n_rollouts, horizon_months + 1)

    assert bundle.rollout_count == n_rollouts
    assert bundle.horizon_months == horizon_months
    assert bundle.metadata.seed == 42
    assert bundle.metadata.model_card_id == "augur-market-model-card:2026-05-15"
    assert bundle.metadata.model_version_id == f"macro-market-model:{provider.label}:unversioned"
    assert bundle.metadata.evidence_set_id == "evidence-set:augur-public-market-data:unversioned"
    assert bundle.metadata.calibration_artifact_id == f"calibration-artifact:in-memory:{provider.label}:unversioned"
    assert bundle.metadata.validation_report_id is None
    assert bundle.metadata.known_limitation_ids == (
        "evidence-set-id-unversioned",
        "calibration-artifact-id-unversioned",
        "constant-mortgage-rate-path",
        "private-equity-marks-flat-fixture",
    )
    assert bundle.metadata.source_metadata["market_provider_label"] == provider.label
    assert "market_provider_seed" not in bundle.metadata.source_metadata
    assert "market_provider_horizon_months" not in bundle.metadata.source_metadata
    np.testing.assert_array_equal(bundle.month_index, np.arange(horizon_months + 1, dtype="int64"))
    for key in (
        "inflation_multipliers",
        "generic_sp500_multipliers",
        "mortgage_30y_rate_pct",
        "private_equity_value_multipliers",
    ):
        values = getattr(bundle, key)
        assert values.shape == expected_shape, key
        assert np.all(np.isfinite(values)), key
    for key in ("inflation_multipliers", "generic_sp500_multipliers", "private_equity_value_multipliers"):
        values = getattr(bundle, key)
        assert_allclose(values[:, 0], 1.0)
        assert np.all(values > 0), key
    expected_locations = {"default", "san_francisco_ca", "vallejo_ca", "mare_island_vallejo_ca"}
    assert set(bundle.home_value_multipliers_by_location) == expected_locations
    assert set(bundle.rent_multipliers_by_location) == expected_locations
    assert_allclose(
        bundle.home_value_multipliers_by_location["san_francisco_ca"],
        bundle.home_value_multipliers_by_location["default"],
    )
    assert_allclose(
        bundle.rent_multipliers_by_location["san_francisco_ca"], bundle.rent_multipliers_by_location["default"]
    )


def test_mortgage_path_constant(provider: MacroMarketBundleProvider) -> None:
    bundle = _sample(provider, rollout_count=1, horizon_months=24)
    arr = bundle.mortgage_30y_rate_pct[0]
    assert_allclose(arr, arr[0])
    assert arr[0] > 0.0


def test_private_equity_paths_flat_with_yearly_tenders(provider: MacroMarketBundleProvider) -> None:
    bundle = _sample(provider, rollout_count=1, horizon_months=24)
    assert_allclose(bundle.private_equity_value_multipliers, 1.0)
    assert not bundle.private_equity_sale_opportunity_mask[:, 0].any()
    assert bundle.private_equity_sale_opportunity_mask[:, 12].all()
    assert bundle.private_equity_sale_opportunity_mask[:, 24].all()


def test_seed_determinism(provider: MacroMarketBundleProvider) -> None:
    request = _request(provider, rollout_count=2, horizon_months=24)
    a = provider.sample_market_bundle(rollout_count=2, horizon_months=24, seed=11, market_request=request)
    b = provider.sample_market_bundle(rollout_count=2, horizon_months=24, seed=11, market_request=request)
    assert_allclose(a.generic_sp500_multipliers, b.generic_sp500_multipliers)


if __name__ == "__main__":
    pytest_bazel.main()
