from __future__ import annotations

from enum import StrEnum

from pydantic import Field, NonNegativeFloat

from augur.core.schemas import ApiModel, Percentage


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


LOCAL_REGULATION_BY_LOCATION: dict[LocationId, LocalRegulation] = {
    LocationId.SAN_FRANCISCO_CA: LocalRegulation(
        property_tax_annual_pct=1.18,
        notes="San Francisco secured property-tax default used by the consolidated house model.",
    ),
    LocationId.VALLEJO_CA: LocalRegulation(
        property_tax_annual_pct=1.1, notes="Vallejo mainland property-tax default around 1.1%."
    ),
    LocationId.MARE_ISLAND_VALLEJO_CA: LocalRegulation(
        property_tax_annual_pct=2.4,
        notes="Mare Island default includes high local special assessments at roughly 2.4%.",
    ),
}


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
