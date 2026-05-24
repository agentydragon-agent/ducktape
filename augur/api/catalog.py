"""Builds the bootstrap payload the augur frontend reads at startup.

Loads the user's property shortlist from `config.property_source.properties_path`
and derives display labels (residence mode, rental use) from `config.agents`
so the same generic code serves any deployment's agents."""

from __future__ import annotations

from collections import Counter

import yaml
from more_itertools import one
from pydantic import TypeAdapter

from augur.api.bootstrap import (
    AgentOption,
    BootstrapResponse,
    Location,
    OwnerResidenceModeId,
    OwnerResidenceModeOption,
    Property,
    RentalUsePolicyId,
    RentalUsePolicyOption,
)
from augur.api.config import Config, LocationConfig, PropertyAssetConfig
from augur.api.finance import FinanceSnapshot
from augur.api.scenario_set import ActorRole
from augur.api.schemas import KnobsConfig
from augur.model.deterministic import Constant, Deterministic
from augur.model.exogenous_provider_config import ExogenousProviderConfig
from augur.model.gbm import GeometricBrownian
from augur.model.independent_exogenous import IndependentExogenousProviderConfig
from augur.model.path_models.models.vecm import VecmExogenousProviderConfig
from augur.model.series import PRIVATE_EQUITY_SERIES_PREFIX, series_suffix
from augur.model.series_model import ScalarSeriesSpec
from augur.product.wire import MAX_HORIZON_MONTHS

PROPERTY_ROWS_ADAPTER = TypeAdapter(tuple[Property, ...])

DEFAULT_KNOBS = KnobsConfig(
    down_payment_pct=25,
    credit_score=776,
    custom_mortgage_rate=6.5,
    custom_mortgage_term_years=30,
    starting_portfolio_usd=0,
    hold_years=5,
    appreciation_rate=2,
    sp500_rate=7,
    maintenance_pct=1,
    owner_occupancy_years=0,
    inflation=3,
    vacancy_pct=5,
    mgmt_pct=8,
    leasing_fee_pct=0,
    rooms_rented_while_living=0,
    room_rent_monthly_usd=0,
    room_vacancy_pct=0,
    portfolio_liquidation_tax_pct=0,
    insurance_annual_usd=1800,
    closing_cost_buy_pct=2.5,
    closing_cost_sell_pct=6.5,
    depreciable_basis_pct=80,
    financing_mode="fixed_30",
    occupancy_type="investment",
)


def _location_from_config(config: LocationConfig) -> Location:
    return Location(
        id=config.location_id,
        label=config.label,
        city=config.city,
        state=config.state,
        local_regulation=config.local_regulation,
        notes=config.notes,
    )


def _locations_for_config(config: Config) -> tuple[Location, ...]:
    locations = tuple(_location_from_config(location) for location in config.locations)
    location_id_counts = Counter(location.id for location in locations)
    duplicate_ids = sorted(location_id for location_id, count in location_id_counts.items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"Augur location catalog has duplicate location ids: {duplicate_ids}")
    return locations


def _validate_property_location(property_: Property, *, location_by_id: dict[str, Location]) -> None:
    if property_.location_id not in location_by_id:
        raise ValueError(f"property {property_.id!r} references unknown location {property_.location_id!r}")


def _public_image_url(asset: PropertyAssetConfig) -> str:
    return str(asset.image_url)


def _apply_property_assets(config: Config, properties: tuple[Property, ...]) -> tuple[Property, ...]:
    property_assets = config.property_source.property_assets
    if not property_assets:
        return properties

    property_ids = {property_.id for property_ in properties}
    unknown_property_ids = sorted(
        asset.property_id for asset in property_assets if asset.property_id not in property_ids
    )
    if unknown_property_ids:
        raise ValueError(f"property_assets reference unknown property ids: {unknown_property_ids}")

    image_url_by_property_id = {asset.property_id: _public_image_url(asset) for asset in property_assets}
    return tuple(
        property_.model_copy(update={"image_url": image_url_by_property_id.get(property_.id, property_.image_url)})
        for property_ in properties
    )


def _default_knobs_for_config(config: Config) -> KnobsConfig:
    starting_portfolio_usd = config.starting_portfolio_usd or config.snapshot.sp500_proxy_portfolio_usd
    return DEFAULT_KNOBS.model_copy(update={"starting_portfolio_usd": starting_portfolio_usd})


def _primary_agent_label(config: Config) -> str:
    """Return the primary-owner label derived from config.agents."""
    primary = one(agent for agent in config.agents if agent.role is ActorRole.PRIMARY_OWNER)
    return primary.label


def _owner_residence_mode_options(primary: str) -> list[OwnerResidenceModeOption]:
    return [
        OwnerResidenceModeOption(
            id=OwnerResidenceModeId.SELECTED_PROPERTY,
            label=f"{primary} lives in selected property",
            description=f"{primary} occupies the selected property for the modeled owner-occupancy period.",
        ),
        OwnerResidenceModeOption(
            id=OwnerResidenceModeId.OTHER_OWNED_PROPERTY,
            label=f"{primary} lives in another modeled property",
            description=(
                f"{primary}'s residence is another selected property while this property can be rented or held."
            ),
        ),
        OwnerResidenceModeOption(
            id=OwnerResidenceModeId.RENTAL_ELSEWHERE,
            label=f"{primary} rents elsewhere",
            description=(f"{primary} does not live in a modeled owned property in this scenario."),
        ),
    ]


def _rental_use_policy_options(primary: str) -> list[RentalUsePolicyOption]:
    return [
        RentalUsePolicyOption(
            id=RentalUsePolicyId.NOT_RENTED,
            label="Not rented",
            description=f"No rental income is modeled while {primary} uses the property.",
        ),
        RentalUsePolicyOption(
            id=RentalUsePolicyId.RENT_ROOMS_WHILE_OWNER_LIVES_THERE,
            label="Rent rooms while living there",
            description=f"Room rental income applies during {primary}'s owner-occupancy period.",
        ),
        RentalUsePolicyOption(
            id=RentalUsePolicyId.RENT_WHOLE_PROPERTY,
            label="Rent whole property",
            description=f"Whole-property rental income applies when the property is not occupied by {primary}.",
        ),
    ]


def _load_properties(config: Config, *, location_by_id: dict[str, Location]) -> tuple[Property, ...]:
    path = config.property_source.properties_path
    # `yaml.safe_load` reads both YAML and JSON (JSON is a YAML subset), so either
    # extension is supported; deployments pick whichever is more ergonomic.
    properties = PROPERTY_ROWS_ADAPTER.validate_python(yaml.safe_load(path.read_text(encoding="utf-8")))
    for property_ in properties:
        _validate_property_location(property_, location_by_id=location_by_id)
    property_id_counts = Counter(property_.id for property_ in properties)
    duplicate_ids = sorted(property_id for property_id, count in property_id_counts.items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"{path} has duplicate property ids: {duplicate_ids}")
    return _apply_property_assets(config, properties)


def build_bootstrap_payload(config: Config) -> BootstrapResponse:
    available_locations = _locations_for_config(config)
    location_by_id = {location.id: location for location in available_locations}
    loaded_properties = _load_properties(config, location_by_id=location_by_id)
    selected_location_ids = (
        set(config.location_selection)
        if config.location_selection is not None
        else {property_.location_id for property_ in loaded_properties}
    )
    unknown_selected_locations = sorted(selected_location_ids - set(location_by_id))
    if unknown_selected_locations:
        raise ValueError(f"location_selection references unknown location ids: {unknown_selected_locations}")
    locations = [location for location in available_locations if location.id in selected_location_ids]
    properties = sorted(
        (property_ for property_ in loaded_properties if property_.location_id in selected_location_ids),
        key=lambda property_: (location_by_id[property_.location_id].city, property_.price_usd, property_.id),
    )
    if not properties:
        raise ValueError("Augur property catalog has no properties after applying location_selection")
    primary = _primary_agent_label(config)
    return BootstrapResponse(
        locations=locations,
        properties=properties,
        default_property_id=properties[0].id,
        default_owner_residence_mode=OwnerResidenceModeId.SELECTED_PROPERTY,
        default_owner_residence_property_id=properties[0].id,
        default_rental_use_policy=RentalUsePolicyId.NOT_RENTED,
        default_initial_checking_usd=config.snapshot.cash_usd,
        default_checking_floor_usd=10_000,
        default_checking_sale_amount_usd=20_000,
        default_knobs=_default_knobs_for_config(config),
        default_rollout_samples=config.default_rollout_samples,
        max_rollout_samples=config.max_rollout_samples,
        max_horizon_months=MAX_HORIZON_MONTHS,
        default_scenarios=list(config.bootstrap_default_scenarios),
        owner_residence_mode_options=_owner_residence_mode_options(primary),
        rental_use_policy_options=_rental_use_policy_options(primary),
        agents=[AgentOption(actor_id=agent.actor_id, label=agent.label, role=agent.role) for agent in config.agents],
        finance_snapshot=_finance_snapshot_with_pe_marks(config),
    )


def _finance_snapshot_with_pe_marks(config: Config) -> FinanceSnapshot:
    """Return the configured `FinanceSnapshot` with `fmv_usd_per_unit` filled
    in on each concentrated holding from the deployment's exogenous provider.

    The snapshot config doesn't repeat per-unit prices (the exogenous provider
    is the source of truth). Bootstrap-time enrichment surfaces the current
    mark so the frontend can render the holding's $value without separately
    asking the simulator for it.
    """
    pe_prices = _pe_unit_prices(config.exogenous_provider)
    return config.snapshot.model_copy(
        update={
            "concentrated_holdings": tuple(
                holding.model_copy(update={"fmv_usd_per_unit": pe_prices.get(holding.holding_id, 0.0)})
                for holding in config.snapshot.concentrated_holdings
            )
        }
    )


def _pe_unit_prices(provider: ExogenousProviderConfig) -> dict[str, float]:
    if isinstance(provider, VecmExogenousProviderConfig):
        return {issuer: float(price) for issuer, price in provider.private_equity_prices_usd.items()}
    if isinstance(provider, IndependentExogenousProviderConfig):
        prices: dict[str, float] = {}
        for series_id, spec in provider.series.items():
            issuer = series_suffix(series_id, PRIVATE_EQUITY_SERIES_PREFIX)
            if issuer is not None:
                prices[issuer] = _t0_level(spec)
        return prices
    return {}


def _t0_level(spec: ScalarSeriesSpec) -> float:
    """Extract the month-0 level from a scalar series spec, dispatching on
    the spec's discriminator. Used to surface the current PE mark for
    bootstrap-time display; no sampling involved."""
    if isinstance(spec, GeometricBrownian):
        return float(spec.initial_value)
    if isinstance(spec, Constant):
        return float(spec.value)
    if isinstance(spec, Deterministic):
        return float(spec.levels[0])
    raise TypeError(f"unsupported ScalarSeriesSpec variant: {type(spec).__name__}")
