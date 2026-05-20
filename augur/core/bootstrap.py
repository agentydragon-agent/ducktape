from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from augur.core.finance import FinanceSnapshot
from augur.core.local_regulation import LocalRegulation
from augur.core.scenario_set import ActorRole, PropertyId
from augur.core.schemas import CoreModel, ScenarioKnobs


class OwnerResidenceModeId(StrEnum):
    SELECTED_PROPERTY = "selected_property"
    OTHER_OWNED_PROPERTY = "other_owned_property"
    RENTAL_ELSEWHERE = "rental_elsewhere"


class RentalUsePolicyId(StrEnum):
    NOT_RENTED = "not_rented"
    RENT_ROOMS_WHILE_OWNER_LIVES_THERE = "rent_rooms_while_owner_lives_there"
    RENT_WHOLE_PROPERTY = "rent_whole_property"


class Option(CoreModel):
    id: str
    label: str
    description: str


class OwnerResidenceModeOption(Option):
    id: OwnerResidenceModeId


class RentalUsePolicyOption(Option):
    id: RentalUsePolicyId


class AgentOption(CoreModel):
    actor_id: str
    label: str
    role: ActorRole


class DefaultScenario(CoreModel):
    property_id: PropertyId
    label: str | None = None


class Location(CoreModel):
    id: str = Field(description="Stable relational location identity used by config, storage, and scenario joins.")
    label: str
    city: str
    state: str
    local_regulation: LocalRegulation
    notes: tuple[str, ...] = ()


class Property(CoreModel):
    """Persistence-shaped property row; join to `BootstrapResponse.locations` by `location_id`."""

    id: str = Field(description="Stable relational property identity used by selection, saved scenarios, and storage.")
    source_catalog_id: str
    source_property_id: str
    location_id: str = Field(description="Foreign key for the property's canonical location row.")
    address: str
    neighborhood: str
    type: str
    price_usd: float
    rent_estimate_usd: float | None = None
    beds: float
    baths: float
    sqft: float
    year_built: int
    hoa_monthly_usd: float = 0
    annual_tax_on_list_usd: float | None = None
    source_url: str | None = None
    image_url: str | None = None
    notes: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


class BootstrapResponse(CoreModel):
    locations: list[Location]
    properties: list[Property]
    default_property_id: str
    default_owner_residence_mode: OwnerResidenceModeId
    default_owner_residence_property_id: str | None = None
    default_rental_use_policy: RentalUsePolicyId
    default_initial_checking_usd: float
    default_checking_floor_usd: float
    default_checking_sale_amount_usd: float
    default_knobs: ScenarioKnobs
    default_rollout_samples: int
    default_scenarios: list[DefaultScenario]
    owner_residence_mode_options: list[OwnerResidenceModeOption]
    rental_use_policy_options: list[RentalUsePolicyOption]
    agents: list[AgentOption]
    finance_snapshot: FinanceSnapshot
