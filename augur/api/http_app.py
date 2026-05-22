from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError

from augur.api.casing import plain_json
from augur.api.scenario_set import ScenarioSet
from augur.product.portfolio import ProductPortfolioResponse
from augur.product.projection import MetricFanRequest, RolloutRequest

PayloadProvider = Callable[[], Any]
ScenarioSetHandler = Callable[[ScenarioSet], Any]
ProductPortfolioHandler = Callable[[], ProductPortfolioResponse]
MetricFanHandler = Callable[[MetricFanRequest], Any]
RolloutHandler = Callable[[RolloutRequest], Any]


def create_augur_backend_app(
    *,
    title: str,
    bootstrap: PayloadProvider,
    product_portfolio: ProductPortfolioHandler,
    product_metric_fan: MetricFanHandler,
    product_rollout: RolloutHandler,
    scenario_set_run: ScenarioSetHandler | None = None,
) -> FastAPI:
    app = FastAPI(title=title)
    no_store = {"cache-control": "no-store"}

    def error(status_code: int, detail: Any) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": detail}, headers=no_store)

    def payload(value: Any) -> JSONResponse:
        return JSONResponse(content=plain_json(value), headers=no_store)

    app.add_exception_handler(RequestValidationError, lambda request, exc: error(422, exc.errors()))
    app.add_exception_handler(ValidationError, lambda request, exc: error(422, exc.errors()))
    app.add_exception_handler(KeyError, lambda request, exc: error(400, str(exc)))
    app.add_exception_handler(ValueError, lambda request, exc: error(400, str(exc)))

    @app.get("/api/bootstrap")
    def bootstrap_house() -> JSONResponse:
        return payload(bootstrap())

    @app.get("/api/product/portfolio")
    def product_portfolio_snapshot() -> JSONResponse:
        return payload(product_portfolio())

    if scenario_set_run is not None:

        @app.post("/api/scenario_sets/run")
        def run_scenario_set(scenario_set: ScenarioSet) -> JSONResponse:
            return payload(scenario_set_run(scenario_set))

    @app.post("/api/product/projections/metric_fan")
    def product_projection_metric_fan(request: MetricFanRequest) -> JSONResponse:
        return payload(product_metric_fan(request))

    @app.post("/api/product/projections/rollout")
    def product_projection_rollout(request: RolloutRequest) -> JSONResponse:
        return payload(product_rollout(request))

    @app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def unknown_api(full_path: str) -> JSONResponse:
        return error(404, f"unknown API endpoint: /api/{full_path}")

    @app.get("/healthz")
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok\n", headers=no_store)

    return app
