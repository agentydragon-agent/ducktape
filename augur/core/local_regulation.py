from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, NonNegativeFloat, model_validator

from augur.core.schemas import ApiModel, Percentage

_LOCAL_REGULATION_DATA_PATH = Path(__file__).with_name("local_regulation.yaml")


class LocationId(StrEnum):
    SAN_FRANCISCO_CA = "san_francisco_ca"
    VALLEJO_CA = "vallejo_ca"
    MARE_ISLAND_VALLEJO_CA = "mare_island_vallejo_ca"


class LocalRegulation(ApiModel):
    property_tax_annual_pct: Percentage = Field(
        description="Annual ad-valorem property-tax rate applied to the Prop 13 assessed value."
    )
    local_transfer_tax_pct: Percentage = Field(
        default=0, description="Local transfer-tax rate applied when the property is sold."
    )
    special_assessment_annual_usd: NonNegativeFloat = Field(
        default=0, description="Fixed annual local special assessment added to property-tax cash flow."
    )
    notes: str = Field(description="Human-readable source and modeling notes for this location.")


class _LocalRegulationData(ApiModel):
    local_regulation_by_location: dict[LocationId, LocalRegulation]

    @model_validator(mode="after")
    def _validate_complete_location_table(self) -> _LocalRegulationData:
        expected = set(LocationId)
        actual = set(self.local_regulation_by_location)
        if actual != expected:
            missing = ", ".join(location_id.value for location_id in LocationId if location_id not in actual) or "none"
            unexpected = ", ".join(sorted(location_id.value for location_id in actual - expected)) or "none"
            expected_list = ", ".join(location_id.value for location_id in LocationId)
            raise ValueError(
                "local_regulation_by_location must define exactly these locations: "
                f"{expected_list}; missing: {missing}; unexpected: {unexpected}"
            )
        return self


def _validate_local_regulation_data(payload: Any) -> _LocalRegulationData:
    return _LocalRegulationData.model_validate(payload)


def _load_local_regulation_data(path: Path = _LOCAL_REGULATION_DATA_PATH) -> _LocalRegulationData:
    return _validate_local_regulation_data(yaml.safe_load(path.read_text(encoding="utf-8")))


LOCAL_REGULATION_BY_LOCATION: dict[LocationId, LocalRegulation] = dict(
    _load_local_regulation_data().local_regulation_by_location
)


def known_location_id(location_id: LocationId | str) -> LocationId | None:
    if isinstance(location_id, LocationId):
        return location_id
    try:
        return LocationId(str(location_id))
    except ValueError:
        return None


def local_regulation_for_location(location_id: LocationId | str) -> LocalRegulation:
    known_id = known_location_id(location_id)
    if known_id is None:
        raise ValueError(f"unknown built-in local regulation for location {location_id!r}")
    return LOCAL_REGULATION_BY_LOCATION[known_id]
