from __future__ import annotations

from enum import StrEnum

from pydantic import Field, NonNegativeFloat

from augur.core.schemas import ApiModel, Percentage


class LocationId(StrEnum):
    LOCATION_A = "location_a"
    LOCATION_B = "location_b"
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
    LocationId.LOCATION_A: LocalRegulation(
        property_tax_annual_pct=1.0,
        notes="Synthetic public fixture location; deployments should supply a real local regulation source.",
    ),
    LocationId.LOCATION_B: LocalRegulation(
        property_tax_annual_pct=1.0,
        notes="Synthetic public fixture location; deployments should supply a real local regulation source.",
    ),
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


def local_regulation_for_location(location_id: LocationId) -> LocalRegulation:
    return LOCAL_REGULATION_BY_LOCATION[location_id]
