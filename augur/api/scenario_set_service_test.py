from __future__ import annotations

from typing import cast

import pytest_bazel

from augur.api.casing import plain_json
from augur.api.catalog import build_bootstrap_payload
from augur.api.config import load_augur_config
from augur.api.scenario_set import RolloutStatusType
from augur.api.scenario_set_service import ScenarioSetService
from augur.api.schemas import Frame
from util.bazel.runfiles import get_required_path


def _floats(frame: Frame, column: str) -> list[float]:
    return cast(list[float], frame[column])


def _service() -> ScenarioSetService:
    config = load_augur_config(get_required_path("_main/augur/api/testdata/config.yaml"))
    bootstrap = build_bootstrap_payload(config)
    return ScenarioSetService(
        portfolio=config.portfolio,
        exogenous_model=config.exogenous_provider.realize_model(),
        properties_by_id={property_.id: property_ for property_ in bootstrap.properties},
        locations_by_id={location.id: location for location in bootstrap.locations},
    )


def test_scenario_set_service_runs_joint_model_and_materializes_graph_tables() -> None:
    service = _service()

    response = service.run_for_request_body(
        {
            "scenario_set_id": "backend_smoke",
            "title": "Backend smoke",
            "sampling_request": {"exogenous_model_id": "simple", "rollout_count": 3, "horizon_months": 3, "seed": 11},
            "scenarios": [
                {
                    "scenario_id": "sp500_spend",
                    "label": "SP500 spend",
                    "actors": [{"actor_id": "agent_a", "label": "Agent A", "role": "primary_owner"}],
                    "initial_balance_sheet": {
                        "accounts": [
                            {
                                "account_id": "checking",
                                "account_type": "checking",
                                "owner_actor_id": "agent_a",
                                "balance_usd": 0.0,
                            }
                        ],
                        "assets": [
                            {
                                "asset_id": "wealthfront_sp500",
                                "asset_type": "generic_sp500_stock",
                                "owner_actor_id": "agent_a",
                                "value_usd": 1000.0,
                                "cost_basis_usd": 700.0,
                            }
                        ],
                    },
                    "policies": [
                        {
                            "policy_id": "monthly_spend",
                            "policy_type": "monthly_spend",
                            "actor_id": "agent_a",
                            "monthly_spend_usd": 100.0,
                        },
                        {
                            "policy_id": "sell_sp500",
                            "policy_type": "checking_floor_sell_public_stock",
                            "actor_id": "agent_a",
                            "floor_usd": 0.0,
                            "sale_amount_usd": 0.0,
                        },
                    ],
                }
            ],
        }
    )

    assert response.sampling_metadata is not None
    assert response.sampling_metadata["exogenous_model_id"] == "independent_exogenous_model"
    assert response.projection_run is not None
    assert response.projection_run.scenario_set_id == "backend_smoke"
    assert response.projection_run.path_set_id.startswith("path_set:")
    assert len(response.projection_run.scenario_input_ids) == 1
    assert [path.rollout_index for path in response.exogenous_paths] == [0, 1, 2]
    assert {path.path_set_id for path in response.exogenous_paths} == {response.projection_run.path_set_id}
    assert {path.exogenous_model_id for path in response.exogenous_paths} == {"independent_exogenous_model"}
    assert len({path.exogenous_path_id for path in response.exogenous_paths}) == 3
    assert all(0 <= path.seed <= 2**32 - 1 for path in response.exogenous_paths)
    result = response.scenario_results[0]
    assert len(result.projection_trajectories) == 3
    assert {trajectory.scenario_id for trajectory in result.projection_trajectories} == {"sp500_spend"}
    assert {trajectory.path_set_id for trajectory in result.projection_trajectories} == {
        response.projection_run.path_set_id
    }
    assert {trajectory.scenario_input_id for trajectory in result.projection_trajectories} == {
        response.projection_run.scenario_input_ids[0]
    }
    assert result.monthly_columns is not None
    assert len(result.monthly_columns["month_index"]) == 12
    assert result.terminal_columns is not None
    assert len(result.terminal_columns["rollout_index"]) == 3
    assert len(result.metric_fan_columns["net_worth_usd"]["month_index"]) == 4
    assert "p05" in result.metric_fan_columns["net_worth_usd"]
    assert "p95" in result.metric_fan_columns["net_worth_usd"]
    assert sum(_floats(result.monthly_columns, "generic_sp500_sale_usd")) > 0
    assert [status.status for status in result.rollout_statuses] == [RolloutStatusType.ACTIVE] * 3

    payload = plain_json(response)
    assert payload["projection_run"]["projection_run_id"].startswith("projection_run:")
    assert len(payload["exogenous_paths"]) == 3
    scenario_payload = payload["scenario_results"][0]
    assert len(scenario_payload["projection_trajectories"]) == 3
    assert len(scenario_payload["metric_fan_columns"]["net_worth_usd"]["month_index"]) == 4
    assert len(scenario_payload["monthly_columns"]["month_index"]) == 12


def test_scenario_set_service_accepts_catalog_defaulted_property_selection() -> None:
    service = _service()

    response = service.run_for_request_body(
        {
            "scenario_set_id": "backend_property_smoke",
            "title": "Backend property smoke",
            "sampling_request": {"exogenous_model_id": "simple", "rollout_count": 3, "horizon_months": 3, "seed": 11},
            "scenarios": [
                {
                    "scenario_id": "buy_catalog_property",
                    "label": "Buy catalog property",
                    "actors": [{"actor_id": "agent_a", "label": "Agent A", "role": "primary_owner"}],
                    "property_selection": {"property_id": "location_a_property"},
                    "financing": {"financing_mode": "fixed_30", "down_payment_pct": 20, "mortgage_rate_pct": 6.5},
                    "initial_balance_sheet": {
                        "accounts": [
                            {
                                "account_id": "checking",
                                "account_type": "checking",
                                "owner_actor_id": "agent_a",
                                "balance_usd": 300_000.0,
                            }
                        ],
                        "assets": [],
                    },
                }
            ],
        }
    )

    result = response.scenario_results[0]
    assert result.summary.property_id == "location_a_property"
    assert result.summary.location_id == "location_a"
    assert result.monthly_columns is not None
    monthly = result.monthly_columns
    assert max(_floats(monthly, "property_value_usd")) == 900_000.0
    assert max(_floats(monthly, "mortgage_balance_usd")) == 720_000.0
    assert sum(_floats(monthly, "purchase_closing_cost_usd")) == 67_500.0
    assert sum(_floats(monthly, "mortgage_payment_usd")) > 0
    assert sum(_floats(monthly, "mortgage_interest_usd")) > 0
    assert sum(_floats(monthly, "mortgage_principal_usd")) > 0
    assert max(_floats(monthly, "home_equity_usd")) > 180_000.0
    assert result.terminal_columns is not None
    assert len(result.terminal_columns["rollout_index"]) == 3


if __name__ == "__main__":
    pytest_bazel.main()
