from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_bazel
from pydantic import ValidationError

import augur.core.schemas as core_schemas
from augur.model.market_config import SourceDataConfig, load_market_config, parse_market_config

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "market_config.example.json"


def _config_payload() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(CONFIG_PATH.read_text(encoding="utf-8")))


def test_source_data_config_is_model_owned() -> None:
    assert SourceDataConfig.__module__ == "augur.model.market_config"
    assert not hasattr(core_schemas, "SourceDataConfig")


def test_load_market_config_rejects_stale_runtime_knobs(tmp_path: Path) -> None:
    payload = _config_payload()
    payload["seed"] = 123
    payload["rollout_count"] = 50
    payload["horizon_months"] = 360
    config_path = tmp_path / "market_config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match=r"seed|rollout_count|horizon_months"):
        load_market_config(config_path)


def test_home_value_location_sources_must_reference_configured_factors() -> None:
    payload = _config_payload()
    payload["location_market_sources"]["home_value"]["unknown_ca"] = "missing_home_factor"

    with pytest.raises(ValidationError, match=r"location_market_sources\.home_value"):
        parse_market_config(payload)


def test_rent_location_sources_must_reference_configured_factors() -> None:
    payload = _config_payload()
    payload["location_market_sources"]["rent"]["unknown_ca"] = "missing_rent_factor"

    with pytest.raises(ValidationError, match=r"location_market_sources\.rent"):
        parse_market_config(payload)


if __name__ == "__main__":
    pytest_bazel.main()
