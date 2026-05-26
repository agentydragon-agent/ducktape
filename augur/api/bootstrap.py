from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, PositiveInt

from augur.api.finance import FinanceSnapshot
from augur.api.local_regulation import LocalRegulation
from augur.api.schemas import ApiModel, KnobsConfig

PropertyId = str


class ActorRole(StrEnum):
    PRIMARY_OWNER = "primary_owner"
    EQUITY_BUILDING_OCCUPANT = "equity_building_occupant"
    TENANT = "tenant"
    LANDLORD = "landlord"


class OwnerResidenceModeId(StrEnum):
    SELECTED_PROPERTY = "selected_property"
    OTHER_OWNED_PROPERTY = "other_owned_property"
    RENTAL_ELSEWHERE = "rental_elsewhere"


class RentalUsePolicyId(StrEnum):
    NOT_RENTED = "not_rented"
    RENT_ROOMS_WHILE_OWNER_LIVES_THERE = "rent_rooms_while_owner_lives_there"
    RENT_WHOLE_PROPERTY = "rent_whole_property"


class Option(ApiModel):
    id: str
    label: str
    description: str


class OwnerResidenceModeOption(Option):
    id: OwnerResidenceModeId


class RentalUsePolicyOption(Option):
    id: RentalUsePolicyId


class AgentOption(ApiModel):
    actor_id: str
    label: str
    role: ActorRole


class DefaultScenario(ApiModel):
    property_id: PropertyId
    label: str | None = None


class Location(ApiModel):
    id: str = Field(description="Stable relational location identity used by config, storage, and scenario joins.")
    label: str
    city: str
    state: str
    local_regulation: LocalRegulation
    notes: tuple[str, ...] = ()


class Property(ApiModel):
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


class ProductInputDefaults(ApiModel):
    """Server-driven overrides for the product input panel's starting values.

    Each field is optional: `None` means "use the frontend's hard-coded base default".
    Deployments (e.g. `gaffer-private`) drop a `product_input_defaults` block into their
    augur YAML to bias the UI toward sensible starting values for their real portfolio
    without touching frontend code. `extra="forbid"` on `ApiModel` catches typos.
    """

    horizon_months: PositiveInt | None = None
    rollout_count: PositiveInt | None = None
    first_seed: int | None = None
    monthly_spend_usd: float | None = None
    spend_index: Literal["inflation", "none"] | None = None
    sell_order: str | None = None
    cash_buffer_trigger_below_usd: float | None = None
    cash_buffer_sale_usd: float | None = None
    cash_buffer_index_to_inflation: bool | None = None
    pe_lnw_floor_usd: float | None = None
    pe_index_floor_to_inflation: bool | None = None
    monthly_rent_usd: float | None = None
    rental_location_id: str | None = None
    property_id: str | None = None
    lives_here: bool | None = None
    financing_kind: Literal["cash", "mortgage"] | None = None
    down_payment_pct: float | None = None
    mortgage_term_months: Literal[180, 360] | None = None
    annual_rate_pct: float | None = None
    annual_insurance_pct: float | None = None
    annual_maintenance_pct: float | None = None
    rental_monthly_usd: float | None = None
    rental_fraction_rented_pct: float | None = None
    rental_vacancy_pct: float | None = None
    use_rental_management: bool | None = None
    management_fee_pct: float | None = None
    leasing_fee_months: float | None = None
    avg_tenancy_months: PositiveInt | None = None


class BootstrapResponse(ApiModel):
    locations: list[Location]
    properties: list[Property]
    default_property_id: str
    default_owner_residence_mode: OwnerResidenceModeId
    default_owner_residence_property_id: str | None = None
    default_rental_use_policy: RentalUsePolicyId
    default_initial_checking_usd: float
    default_checking_floor_usd: float
    default_checking_sale_amount_usd: float
    default_knobs: KnobsConfig
    default_rollout_samples: PositiveInt
    max_rollout_samples: PositiveInt
    max_horizon_months: PositiveInt
    default_scenarios: list[DefaultScenario]
    owner_residence_mode_options: list[OwnerResidenceModeOption]
    rental_use_policy_options: list[RentalUsePolicyOption]
    agents: list[AgentOption]
    finance_snapshot: FinanceSnapshot
    product_input_defaults: ProductInputDefaults = Field(default_factory=ProductInputDefaults)
