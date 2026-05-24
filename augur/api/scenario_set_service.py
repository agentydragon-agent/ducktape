"""Scenario-set runner. Translates request scenarios, samples exogenous, runs sim, builds response."""

from __future__ import annotations

from typing import Any

from augur.api.bootstrap import Location, Property
from augur.api.bridge import sample_exogenous_for_translations, translate_scenario_set
from augur.api.portfolio import PortfolioConfig
from augur.api.response import scenario_set_response_from_runs
from augur.api.scenario_set import Scenario, ScenarioSet, ScenarioSetRunResponse
from augur.api.scenario_tax_defaults import scenario_with_location_tax_defaults
from augur.model.exogenous import Sampler
from augur.sim.external_series import materialize_sampled_exogenous
from augur.sim.simulate import simulate_with_external_series


class ScenarioSetService:
    def __init__(
        self,
        *,
        portfolio: PortfolioConfig,
        exogenous_model: Sampler,
        properties_by_id: dict[str, Property],
        locations_by_id: dict[str, Location],
    ) -> None:
        self._portfolio = portfolio
        self._exogenous_model = exogenous_model
        self._properties_by_id = properties_by_id
        self._locations_by_id = locations_by_id

    def run_for_request_body(self, body: dict[str, Any]) -> ScenarioSetRunResponse:
        return self.run(ScenarioSet.model_validate(body))

    def run(self, scenario_set: ScenarioSet) -> ScenarioSetRunResponse:
        self._validate_property_references(scenario_set)
        scenario_set = self.with_catalog_defaults(scenario_set)
        translations = translate_scenario_set(scenario_set, configured_lots=self._portfolio.to_initial_lots())
        sampled = sample_exogenous_for_translations(
            self._exogenous_model,
            translations,
            sampling_request=scenario_set.sampling_request,
            level_anchors=self._portfolio.level_anchors,
        )
        external_series = materialize_sampled_exogenous(sampled)
        simulation_runs = {
            translation.scenario_id: simulate_with_external_series(
                translation.scenario,
                rollout_count=scenario_set.sampling_request.rollout_count,
                external_series=external_series,
            )
            for translation in translations
        }
        return scenario_set_response_from_runs(
            scenario_set=scenario_set, simulation_runs=simulation_runs, sampled_exogenous_metadata=sampled.metadata
        )

    def _validate_property_references(self, scenario_set: ScenarioSet) -> None:
        for scenario in scenario_set.scenarios:
            property_id = scenario.property_selection.property_id
            if property_id is None:
                continue
            property_ = self._properties_by_id[property_id]
            requested_location = scenario.property_selection.location_id
            if requested_location is not None and str(requested_location) != property_.location_id:
                raise ValueError(
                    "scenario property/location mismatch: "
                    f"{scenario.scenario_id} uses {property_id!r} with {requested_location!r}"
                )

    def with_catalog_defaults(self, scenario_set: ScenarioSet) -> ScenarioSet:
        scenarios: list[Scenario] = []
        for scenario in scenario_set.scenarios:
            property_id = scenario.property_selection.property_id
            if property_id is None:
                scenarios.append(scenario)
                continue
            property_ = self._properties_by_id[property_id]
            location = self._locations_by_id[property_.location_id]
            with_catalog_property = scenario.model_copy(
                update={
                    "property_selection": scenario.property_selection.model_copy(
                        update={
                            "location_id": scenario.property_selection.location_id or property_.location_id,
                            "purchase_price_usd": scenario.property_selection.purchase_price_usd
                            if scenario.property_selection.purchase_price_usd is not None
                            else property_.price_usd,
                        }
                    )
                }
            )
            scenarios.append(scenario_with_location_tax_defaults(with_catalog_property, location.local_regulation))
        return scenario_set.model_copy(update={"scenarios": tuple(scenarios)})
