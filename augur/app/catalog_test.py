"""Bootstrap catalog tests for public-safe fixture composition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest_bazel

from augur.app.catalog import build_bootstrap_payload
from augur.app.config import AgentDefinition, AugurConfig, FinanceSnapshot, PersonalFinanceConfig, PropertyCatalogConfig
from augur.core.local_regulation import LocationId
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


def _config(properties_path: Path, *, location_selection: tuple[LocationId, ...] | None = None) -> AugurConfig:
    return AugurConfig(
        agents=(AgentDefinition(actor_id="agent_a", label="Agent A", role=ActorRole.PRIMARY_OWNER),),
        personal_finance=PersonalFinanceConfig(cash_usd=0),
        property_catalog=PropertyCatalogConfig(properties_path=properties_path),
        snapshot=FinanceSnapshot(as_of_date="2026-05-14"),
        location_selection=location_selection,
    )


def test_bootstrap_locations_default_to_loaded_property_catalog(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)

    bootstrap = build_bootstrap_payload(_config(properties_path))

    assert [location.id for location in bootstrap.locations] == [LocationId.LOCATION_A, LocationId.LOCATION_B]
    assert [property_.id for property_ in bootstrap.properties] == ["location_a_property", "location_b_property"]


def test_bootstrap_location_selection_filters_properties_and_locations(tmp_path: Path) -> None:
    properties_path = tmp_path / "properties.json"
    _write_properties(properties_path)

    bootstrap = build_bootstrap_payload(_config(properties_path, location_selection=(LocationId.LOCATION_A,)))

    assert [location.id for location in bootstrap.locations] == [LocationId.LOCATION_A]
    assert [property_.id for property_ in bootstrap.properties] == ["location_a_property"]


if __name__ == "__main__":
    pytest_bazel.main()
