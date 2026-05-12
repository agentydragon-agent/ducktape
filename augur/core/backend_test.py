from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest_bazel

from augur.core.backend import create_augur_backend_app


class _Request:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    async def json(self) -> dict[str, Any]:
        return self.body


def test_scenario_set_route_is_registered_and_invokes_handler() -> None:
    seen_body: dict[str, Any] | None = None

    def scenario_set_run(body: dict[str, Any]) -> dict[str, Any]:
        nonlocal seen_body
        seen_body = body
        return {
            "scenario_set_id": body["scenario_set_id"],
            "scenario_results": [{"scenario_id": body["scenarios"][0]["scenario_id"], "status": "not_yet_simulated"}],
        }

    app = create_augur_backend_app(title="test", bootstrap=lambda: {"ok": True}, scenario_set_run=scenario_set_run)
    assert not any(getattr(route, "path", None) == "/api/projection/run" for route in app.routes)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/scenario_sets/run")
    response = asyncio.run(
        route.endpoint(_Request({"scenario_set_id": "route_test", "scenarios": [{"scenario_id": "sf_house"}]}))
    )

    assert seen_body == {"scenario_set_id": "route_test", "scenarios": [{"scenario_id": "sf_house"}]}
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["scenario_set_id"] == "route_test"
    assert payload["scenario_results"][0]["scenario_id"] == "sf_house"


if __name__ == "__main__":
    pytest_bazel.main()
