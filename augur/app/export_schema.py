"""Export the Augur API OpenAPI schema to stdout."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from augur.core.bootstrap import BootstrapResponse
from augur.core.scenario_set import ScenarioSet, ScenarioSetRunResponse


def create_schema_app() -> FastAPI:
    app = FastAPI(title="Augur scenario API")

    @app.get("/api/bootstrap", response_model=BootstrapResponse)
    def bootstrap() -> BootstrapResponse:
        raise RuntimeError("schema-only route")

    @app.post("/api/scenario_sets/run", response_model=ScenarioSetRunResponse)
    def run_scenario_set(scenario_set: ScenarioSet) -> ScenarioSetRunResponse:
        raise RuntimeError("schema-only route")

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok\n"

    return app


def main() -> None:
    print(json.dumps(create_schema_app().openapi(), indent=2))


if __name__ == "__main__":
    main()
