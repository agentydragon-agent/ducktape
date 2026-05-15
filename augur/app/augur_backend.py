"""Generic augur backend: builds the bootstrap payload and runs scenario
sets through the vectorized engine. User-specific data is read from the
`AugurConfig` passed at construction time."""

from __future__ import annotations

from typing import Any

from augur.app.catalog import build_bootstrap_payload
from augur.app.config import AugurConfig
from augur.core.api import simulate_set
from augur.core.augur_accounting import MONTHS_PER_YEAR
from augur.core.bootstrap import ActorPolicyId, Property
from augur.core.local_regulation import LocationId, known_location_id
from augur.core.market_bundle import HorizonBoundMarketBundleProvider, MarketBundleProvider, SimpleMarketBundleProvider
from augur.core.scenario_set import OccupancyMode, RentalMode, Scenario, ScenarioSet, ScenarioSetRunResponse, TaxRegime
from augur.core.schemas import ScenarioKnobs


class AugurBackend:
    def __init__(
        self,
        *,
        augur_config: AugurConfig,
        default_rollout_samples: int | None = None,
        max_rollout_samples: int = 2048,
        default_property_id: str | None = None,
        default_actor_policy: ActorPolicyId | None = None,
        market_bundle_provider: MarketBundleProvider | None = None,
    ) -> None:
        self.market_bundle_provider = market_bundle_provider or SimpleMarketBundleProvider()
        self._bootstrap = build_bootstrap_payload(augur_config)
        self._property_by_id: dict[str, Property] = {
            property_.id: property_ for property_ in self._bootstrap.properties
        }
        self._location_by_id = {location.id: location for location in self._bootstrap.locations}
        self.default_rollout_samples = default_rollout_samples or self._bootstrap.default_rollout_samples
        self.max_rollout_samples = max_rollout_samples
        self.default_knobs = self._default_knobs_for_provider(self._bootstrap.default_knobs)
        self.default_property_id = default_property_id or self._bootstrap.default_property_id
        self.default_actor_policy = default_actor_policy or self._bootstrap.default_actor_policy

    def bootstrap_payload(self):
        return self._bootstrap.model_copy(
            update={
                "default_property_id": self.default_property_id,
                "default_actor_policy": self.default_actor_policy,
                "default_knobs": self.default_knobs,
                "default_rollout_samples": self.default_rollout_samples,
            }
        )

    def run_scenario_set_for_request_body(self, body: dict[str, Any]) -> ScenarioSetRunResponse:
        scenario_set = ScenarioSet.model_validate(body)
        self._validate_scenario_set_property_references(scenario_set)
        scenario_set = self._scenario_set_with_catalog_defaults(scenario_set)
        return simulate_set(scenario_set, market_provider=self.market_bundle_provider).to_response()

    def _default_knobs_for_provider(self, knobs: ScenarioKnobs) -> ScenarioKnobs:
        if not isinstance(self.market_bundle_provider, HorizonBoundMarketBundleProvider):
            return knobs
        max_hold_years = max(1, self.market_bundle_provider.horizon_months // MONTHS_PER_YEAR)
        return knobs.model_copy(update={"hold_years": min(knobs.hold_years, max_hold_years)})

    def _validate_scenario_set_property_references(self, scenario_set: ScenarioSet) -> None:
        for scenario in scenario_set.scenarios:
            property_id = scenario.property_selection.property_id
            if property_id is None:
                continue
            property_ = self._property_by_id[property_id]
            requested_location = scenario.property_selection.location_id
            if requested_location is not None and str(requested_location) != property_.location_id:
                raise ValueError(
                    "scenario property/location mismatch: "
                    f"{scenario.scenario_id} uses {property_id!r} with {requested_location!r}"
                )

    def _scenario_set_with_catalog_defaults(self, scenario_set: ScenarioSet) -> ScenarioSet:
        scenarios: list[Scenario] = []
        for scenario in scenario_set.scenarios:
            property_id = scenario.property_selection.property_id
            if property_id is None:
                scenarios.append(scenario)
                continue
            property_ = self._property_by_id[property_id]
            selection = scenario.property_selection.model_copy(
                update={
                    "location_id": scenario.property_selection.location_id or property_.location_id,
                    "local_regulation": scenario.property_selection.local_regulation
                    or self._location_by_id[property_.location_id].local_regulation,
                    "purchase_price_usd": scenario.property_selection.purchase_price_usd
                    if scenario.property_selection.purchase_price_usd is not None
                    else property_.price_usd,
                    "tax_regime": scenario.property_selection.tax_regime
                    or tax_regime_for_location(property_.location_id),
                }
            )
            scenarios.append(
                scenario.model_copy(
                    update={
                        "property_selection": selection,
                        "tax_regimes": _tax_regimes_with_catalog_defaults(scenario, property_.location_id),
                    }
                )
            )
        return scenario_set.model_copy(update={"scenarios": tuple(scenarios)})


def tax_regime_for_location(location_id: LocationId | str) -> TaxRegime:
    known_id = known_location_id(location_id)
    if known_id is LocationId.MARE_ISLAND_VALLEJO_CA:
        return TaxRegime.MARE_ISLAND_SPECIAL_ASSESSMENTS
    if known_id is LocationId.VALLEJO_CA:
        return TaxRegime.VALLEJO_PROPERTY_TAX
    if known_id is LocationId.SAN_FRANCISCO_CA:
        return TaxRegime.SAN_FRANCISCO_SECURED_PROPERTY_TAX
    return TaxRegime.CALIFORNIA_PROP13


def _tax_regimes_with_catalog_defaults(scenario: Scenario, location_id: LocationId | str) -> tuple[TaxRegime, ...]:
    known_id = known_location_id(location_id)
    regimes = [
        *scenario.tax_regimes,
        TaxRegime.CALIFORNIA_PROP13,
        TaxRegime.CALIFORNIA_TRANSFER_TAX,
        TaxRegime.FEDERAL_MORTGAGE_INTEREST,
        TaxRegime.FEDERAL_CAPITAL_GAINS,
        TaxRegime.CALIFORNIA_INCOME_TAX,
        tax_regime_for_location(location_id),
    ]
    if known_id is LocationId.SAN_FRANCISCO_CA:
        regimes.append(TaxRegime.SAN_FRANCISCO_TRANSFER_TAX)
    if (
        scenario.occupancy_plan.occupancy_mode is OccupancyMode.OWNER_LIVES_IN_PROPERTY
        and scenario.rental_plan.rental_mode is not RentalMode.RENT_WHOLE_PROPERTY
    ):
        regimes.append(TaxRegime.CALIFORNIA_OWNER_OCCUPIED)
        regimes.append(TaxRegime.PRIMARY_RESIDENCE_EXCLUSION)
    else:
        regimes.append(TaxRegime.CALIFORNIA_INVESTMENT_PROPERTY)
    if scenario.rental_plan.rental_mode is not RentalMode.NOT_RENTED:
        regimes.append(TaxRegime.RENTAL_DEPRECIATION)
        regimes.append(TaxRegime.DEPRECIATION_RECAPTURE)
    return tuple(dict.fromkeys(regimes))
