"""Round-trip test: train the active VECM model offline, write the provider config +
blob, re-load via Pydantic + `<Model>MarketProviderConfig.realize(...)`, and
sample.

This is the public contract the augur server consumes at startup: read
`AugurConfig.market_provider`, dispatch via the discriminated union, and
sample without re-fitting from source CSVs."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel
import yaml
from pydantic import TypeAdapter

from augur.core.market_bundle import RequiredMarketKeys
from augur.core.scenario_set import MarketRequest
from augur.model.market_provider_config import (
    MarketProviderConfig,
    NoopMarketProviderConfig,
    SimpleMarketProviderConfig,
)
from augur.model.train import main as train_main
from util.bazel.runfiles import get_required_path

_ADAPTER: TypeAdapter[MarketProviderConfig] = TypeAdapter(MarketProviderConfig)
_MARKET_CONFIG_RUNFILE = "_main/augur/model/config/market_config.example.json"


@pytest.mark.parametrize("model_label", ["vecm"])
def test_train_then_load_and_sample(model_label: str, tmp_path: Path) -> None:
    out_manifest = tmp_path / "market_provider.yaml"
    out_blob = tmp_path / f"trained_{model_label}.npz"

    train_main(
        [
            "--market-config",
            str(get_required_path(_MARKET_CONFIG_RUNFILE)),
            "--model",
            model_label,
            "--out-provider-config",
            str(out_manifest),
            "--out-blob",
            str(out_blob),
        ]
    )

    assert out_manifest.exists()
    assert out_blob.exists()

    parsed = _ADAPTER.validate_python(yaml.safe_load(out_manifest.read_text(encoding="utf-8")))
    # Trainer only emits the active trained provider config; narrow away fixture
    # providers so the trained-provider fields are accessible below.
    assert not isinstance(parsed, (NoopMarketProviderConfig, SimpleMarketProviderConfig))
    assert parsed.type == model_label
    assert parsed.trained_blob == out_blob
    assert parsed.latest_observations  # non-empty; exact keys depend on the source-data schema

    provider = parsed.realize(current_private_equity_price_usd=100.0)
    locations = frozenset(parsed.location_market_sources.home_value)
    bundle = provider.sample_market_bundle(
        rollout_count=2,
        horizon_months=12,
        seed=7,
        market_request=MarketRequest(market_model_id=model_label, rollout_count=2, horizon_months=12, seed=7),
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
