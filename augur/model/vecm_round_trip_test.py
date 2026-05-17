"""Round-trip test: train a VECM offline, write the provider config + blob,
re-load via Pydantic + `VecmMarketProviderConfig.realize(...)`, and sample.

Covers the full deployment workflow — ducktape's example market_config +
source CSVs → `augur/model/train.py` → manifest YAML + npz blob →
`MarketProviderConfig` parser → `MacroMarketBundleProvider` → sampled
`MarketBundle`. The augur server consumes this same path at startup."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel
import yaml
from pydantic import TypeAdapter

from augur.core.market_bundle import RequiredMarketKeys
from augur.core.scenario_set import MarketRequest
from augur.model.market_provider_config import MarketProviderConfig, VecmMarketProviderConfig
from augur.model.train import main as train_main
from util.bazel.runfiles import get_required_path

_ADAPTER: TypeAdapter[MarketProviderConfig] = TypeAdapter(MarketProviderConfig)


def test_train_then_load_and_sample(tmp_path: Path) -> None:
    market_config = get_required_path("_main/augur/model/config/market_config.example.json")
    out_manifest = tmp_path / "market_provider.yaml"
    out_blob = tmp_path / "trained_vecm.npz"

    train_main(
        [
            "--market-config",
            str(market_config),
            "--model",
            "vecm",
            "--out-provider-config",
            str(out_manifest),
            "--out-blob",
            str(out_blob),
        ]
    )

    assert out_manifest.exists()
    assert out_blob.exists()

    parsed = _ADAPTER.validate_python(yaml.safe_load(out_manifest.read_text(encoding="utf-8")))
    assert isinstance(parsed, VecmMarketProviderConfig)
    assert parsed.trained_blob == out_blob
    assert parsed.latest_observations  # non-empty — exact keys depend on the source-data schema

    provider = parsed.realize(current_private_equity_price_usd=100.0)
    locations = frozenset(parsed.location_market_sources.home_value)
    bundle = provider.sample_market_bundle(
        rollout_count=2,
        horizon_months=12,
        seed=7,
        market_request=MarketRequest(market_model_id="vecm", rollout_count=2, horizon_months=12, seed=7),
        required_keys=RequiredMarketKeys(location_ids=locations),
    )

    assert bundle.rollout_count == 2
    assert bundle.horizon_months == 12
    assert bundle.metadata.market_model_version_id.startswith("model_version:")
    assert set(bundle.home_value_multipliers_by_location) == locations
    assert set(bundle.rent_multipliers_by_location) == locations
    assert bundle.metadata.current_private_equity_price_usd == 100.0


if __name__ == "__main__":
    pytest_bazel.main()
