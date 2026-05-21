from __future__ import annotations

import pytest_bazel
from fastapi.testclient import TestClient

from augur.api.http_app import create_augur_backend_app
from augur.api.scenario_set import ScenarioSet
from augur.product.projection import ProjectionRequest


def _scenario_set_body() -> dict:
    return {
        "scenario_set_id": "route_test",
        "title": "Route test",
        "sampling_request": {"rollout_count": 1, "horizon_months": 1, "seed": 1},
        "scenarios": [
            {
                "scenario_id": "sf_house",
                "label": "SF house",
                "actors": [{"actor_id": "owner", "label": "Owner", "role": "primary_owner"}],
            }
        ],
    }


def _product_projection_run(request: ProjectionRequest) -> dict:
    return {
        "exogenous_model_id": request.exogenous_model_id,
        "horizon_months": request.horizon_months,
        "rollouts": [
            {
                "seed": int(request.rollout_seeds[0]),
                "failed": False,
                "monthly_metrics": {"row_count": 1, "columns": {"month_index": [0], "cash_usd": [50000.0]}},
                "terminal_metrics": {
                    "cash_usd": 50000.0,
                    "net_worth_usd": 50000.0,
                    "drawdown_usd": 0.0,
                    "shortfall_usd": 0.0,
                },
            }
        ],
    }


def test_scenario_set_route_is_registered_and_invokes_handler() -> None:
    seen_scenario_set: ScenarioSet | None = None

    def scenario_set_run(scenario_set: ScenarioSet) -> dict:
        nonlocal seen_scenario_set
        seen_scenario_set = scenario_set
        return {
            "scenario_set_id": scenario_set.scenario_set_id,
            "scenario_results": [{"scenario_id": scenario_set.scenarios[0].scenario_id}],
        }

    app = create_augur_backend_app(
        title="test",
        bootstrap=lambda: {"ok": True},
        product_projection_run=_product_projection_run,
        scenario_set_run=scenario_set_run,
    )
    assert not any(getattr(route, "path", None) == "/api/projection/run" for route in app.routes)
    response = TestClient(app).post("/api/scenario_sets/run", json=_scenario_set_body())

    assert response.status_code == 200
    assert seen_scenario_set is not None
    assert seen_scenario_set.scenario_set_id == "route_test"
    assert seen_scenario_set.scenarios[0].scenario_id == "sf_house"
    payload = response.json()
    assert payload["scenario_set_id"] == "route_test"
    assert payload["scenario_results"][0]["scenario_id"] == "sf_house"


def test_scenario_set_route_validates_request_with_pydantic() -> None:
    called = False

    def scenario_set_run(scenario_set: ScenarioSet) -> dict:
        nonlocal called
        called = True
        return {"scenario_set_id": scenario_set.scenario_set_id, "scenario_results": []}

    app = create_augur_backend_app(
        title="test",
        bootstrap=lambda: {"ok": True},
        product_projection_run=_product_projection_run,
        scenario_set_run=scenario_set_run,
    )
    response = TestClient(app).post("/api/scenario_sets/run", json={"scenario_set_id": "missing_required_fields"})

    assert response.status_code == 422
    assert not called


if __name__ == "__main__":
    pytest_bazel.main()
