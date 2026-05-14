from __future__ import annotations

from enum import StrEnum

from augur.core.local_regulation import LocalRegulation, LocationId
from augur.core.scenario_set import ActorRole, PropertyId
from augur.core.schemas import ApiModel, ScenarioKnobs


class ActorPolicyId(StrEnum):
    OWNER_ONLY = "owner_only"
    OWNER_PLUS_PARTNER = "owner_plus_partner"


class OwnerResidenceModeId(StrEnum):
    SELECTED_PROPERTY = "selected_property"
    OTHER_OWNED_PROPERTY = "other_owned_property"
    RENTAL_ELSEWHERE = "rental_elsewhere"


class RentalUsePolicyId(StrEnum):
    NOT_RENTED = "not_rented"
    RENT_ROOMS_WHILE_OWNER_LIVES_THERE = "rent_rooms_while_owner_lives_there"
    RENT_WHOLE_PROPERTY = "rent_whole_property"


class LiquidReservePolicyId(StrEnum):
    NONE = "none"
    CHECKING_FLOOR_SP500 = "checking_floor_sp500"


class HomeValueFactorId(StrEnum):
    LOCATION_A_HOME = "location_a_home"
    LOCATION_B_HOME = "location_b_home"
    SF_HOME = "sf_home"
    VALLEJO_HOME = "vallejo_home"


class RentFactorId(StrEnum):
    LOCATION_A_RENT = "location_a_rent"
    LOCATION_B_RENT = "location_b_rent"
    SF_RENT = "sf_rent"
    VALLEJO_RENT = "vallejo_rent"


class Option(ApiModel):
    id: str
    label: str
    description: str


class ActorPolicyOption(Option):
    id: ActorPolicyId


class OwnerResidenceModeOption(Option):
    id: OwnerResidenceModeId


class RentalUsePolicyOption(Option):
    id: RentalUsePolicyId


class LiquidReservePolicyOption(Option):
    id: LiquidReservePolicyId


class AgentOption(ApiModel):
    actor_id: str
    label: str
    role: ActorRole


class DefaultScenario(ApiModel):
    property_id: PropertyId
    actor_policy: ActorPolicyId
    label: str | None = None


class Location(ApiModel):
    id: LocationId
    label: str
    city: str
    state: str
    home_value_factor_id: HomeValueFactorId
    rent_factor_id: RentFactorId
    local_regulation: LocalRegulation
    notes: tuple[str, ...] = ()


class PropertyRecord(ApiModel):
    id: str
    source_catalog_id: str
    source_property_id: str
    location_id: LocationId
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


class Property(PropertyRecord):
    location: Location


class BootstrapResponse(ApiModel):
    locations: list[Location]
    properties: list[Property]
    default_property_id: str
    default_actor_policy: ActorPolicyId
    default_owner_residence_mode: OwnerResidenceModeId
    default_owner_residence_property_id: str | None = None
    default_rental_use_policy: RentalUsePolicyId
    default_liquid_reserve_policy: LiquidReservePolicyId
    default_initial_checking_usd: float
    default_checking_floor_usd: float
    default_checking_sale_amount_usd: float
    default_knobs: ScenarioKnobs
    default_rollout_samples: int
    default_scenarios: list[DefaultScenario]
    actor_policy_options: list[ActorPolicyOption]
    owner_residence_mode_options: list[OwnerResidenceModeOption]
    rental_use_policy_options: list[RentalUsePolicyOption]
    liquid_reserve_policy_options: list[LiquidReservePolicyOption]
    agents: list[AgentOption]
    default_partner_monthly_payment_usd: float = 0
