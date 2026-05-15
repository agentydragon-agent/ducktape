"""Bootstrap catalog tests for public-safe fixture composition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_bazel

from augur.app.catalog import build_bootstrap_payload
from augur.app.config import (
    AgentDefinition,
    AugurConfig,
    ConcentratedHoldingConfig,
    ConcentratedHoldingSnapshot,
    FinanceSnapshot,
    LocationConfig,
    PersonalFinanceConfig,
    PropertySourceConfig,
)
from augur.core.local_regulation import LocalRegulation
from augur.core.scenario_set import ActorRole


def _write_properties(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "id": "location_a_property",
                    "source_catalog_id": "public_fixture",
                    "source_property_id": "location-a-property",
                    "location_id": "location_a",
                    "address": "Location A Property",
                    "neighborhood": "Location A",
                    "type": "Fixture",
                    "price_usd": 900000,
                    "rent_estimate_usd": 4200,
                    "beds": 3,
                    "baths": 2,
                    "sqft": 1400,
                    "year_built": 2000,
                },
                {
                    "id": "location_b_property",
                    "source_catalog_id": "public_fixture",
                    "source_property_id": "location-b-property",
                    "location_id": "location_b",
                    "address": "Location B Property",
                    "neighborhood": "Location B",
                    "type": "Fixture",
                    "price_usd": 520000,
                    "rent_estimate_usd": 3100,
                    "beds": 3,
                    "baths": 2,
                    "sqft": 1250,
                    "year_built": 2000,
                },
            ]
        ),
        encoding="utf-8",
    )


def _fixture_locations() -> tuple[LocationConfig, ...]:
    regulation = LocalRegulation(property_tax_annual_pct=1.0, notes="Synthetic public fixture location.")
    return (
        LocationConfig(
            location_id="location_a",
            label="Location A",
            city="Location A",
            state="Fixture",
            local_regulation=regulation,
            notes=("Synthetic public fixture location.",),
        ),
        LocationConfig(
            location_id="location_b",
            label="Location B",
            city="Location B",
            state="Fixture",
            local_regulation=regulation,
            notes=("Synthetic public fixture location.",),
        ),
    )


def _config(properties_path: Path, *, location_selection: tuple[str, ...] | None = None) -> AugurConfig:
    return AugurConfig(
        agents=(AgentDefinition(actor_id="agent_a", label="Agent A", role=ActorRole.PRIMARY_OWNER),),
        personal_finance=PersonalFinanceConfig(
            cash_usd=12_345,
            concentrated_holdings=(
                ConcentratedHoldingConfig(
                    holding_id="private_holding_a", label="Private Holding A", units=500, basis_per_unit_usd=5
                ),
            ),
        ),
        property_source=PropertySourceConfig(properties_path=properties_path),
        snapshot=FinanceSnapshot(
            as_of_date="2026-05-14",
            cash_usd=12_345,
            wealthfront_sp500_usd=61_000,
            ibkr_vt_usd=39_000,
            sp500_proxy_portfolio_usd=100_000,
            concentrated_holdings=(
                ConcentratedHoldingSnapshot(
                    holding_id="private_holding_a", units=500, fmv_usd_per_unit=20, valuation_source="fixture mark"
                ),
            ),
        ),
        starting_portfolio_usd=100_000,
        locations=_fixture_locations(),
        location_selection=location_selection,
    )


def test_bootstrap_locations_default_to_loaded_property_source(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)

    bootstrap = build_bootstrap_payload(_config(properties_path))

    assert [location.id for location in bootstrap.locations] == ["location_a", "location_b"]
    assert [property_.id for property_ in bootstrap.properties] == ["location_a_property", "location_b_property"]


def test_bootstrap_location_selection_filters_properties_and_locations(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)

    bootstrap = build_bootstrap_payload(_config(properties_path, location_selection=("location_a",)))

    assert [location.id for location in bootstrap.locations] == ["location_a"]
    assert [property_.id for property_ in bootstrap.properties] == ["location_a_property"]


def test_bootstrap_carries_configured_finance_snapshot_and_defaults(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)

    bootstrap = build_bootstrap_payload(_config(properties_path))

    assert bootstrap.default_initial_checking_usd == 12_345
    assert bootstrap.default_knobs.starting_portfolio_usd == 100_000
    assert bootstrap.finance_snapshot.cash_usd == 12_345
    assert bootstrap.finance_snapshot.wealthfront_sp500_usd == 61_000
    assert bootstrap.finance_snapshot.ibkr_vt_usd == 39_000
    assert bootstrap.finance_snapshot.sp500_proxy_portfolio_usd == 100_000
    assert bootstrap.finance_snapshot.concentrated_holdings[0].label == "Private Holding A"
    assert bootstrap.finance_snapshot.concentrated_holdings[0].units == 500
    assert bootstrap.finance_snapshot.concentrated_holdings[0].value_usd == 10_000


def test_bootstrap_rejects_unknown_property_location(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)
    records = json.loads(properties_path.read_text(encoding="utf-8"))
    records[0]["location_id"] = "missing_location"
    properties_path.write_text(json.dumps(records), encoding="utf-8")

    with pytest.raises(
        ValueError, match="property 'location_a_property' references unknown location 'missing_location'"
    ):
        build_bootstrap_payload(_config(properties_path))


def test_bootstrap_rejects_unknown_location_selection(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)

    with pytest.raises(ValueError, match="location_selection references unknown location ids"):
        build_bootstrap_payload(_config(properties_path, location_selection=("missing_location",)))


def test_bootstrap_rejects_duplicate_config_location_ids(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)
    config = _config(properties_path).model_copy(
        update={"locations": (_fixture_locations()[0], _fixture_locations()[0])}
    )

    with pytest.raises(ValueError, match="duplicate location ids"):
        build_bootstrap_payload(config)


if __name__ == "__main__":
    pytest_bazel.main()
