from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import ValidationError

from augur.api.casing import plain_json

StaticPathResolver = Callable[[str], Path]
PayloadProvider = Callable[[], Any]
RequestPayloadHandler = Callable[[dict[str, Any]], Any]


def create_augur_backend_app(
    *,
    title: str,
    static_path: StaticPathResolver | None = None,
    bootstrap: PayloadProvider,
    scenario_set_run: RequestPayloadHandler | None = None,
) -> FastAPI:
    app = FastAPI(title=title)
    no_store = {"cache-control": "no-store"}

    def error(status_code: int, detail: Any) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": detail}, headers=no_store)

    def payload(value: Any) -> JSONResponse:
        return JSONResponse(content=plain_json(value), headers=no_store)

    def request_body(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    app.add_exception_handler(RequestValidationError, lambda request, exc: error(422, exc.errors()))
    app.add_exception_handler(ValidationError, lambda request, exc: error(422, exc.errors()))
    app.add_exception_handler(KeyError, lambda request, exc: error(400, str(exc)))
    app.add_exception_handler(ValueError, lambda request, exc: error(400, str(exc)))

    @app.get("/api/bootstrap")
    def bootstrap_house() -> JSONResponse:
        return payload(bootstrap())

    if scenario_set_run is not None:

        @app.post("/api/scenario_sets/run")
        async def run_scenario_set(request: Request) -> JSONResponse:
            body = await request.json()
            return payload(scenario_set_run(request_body(body)))

    @app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def unknown_api(full_path: str) -> JSONResponse:
        return error(404, f"unknown API endpoint: /api/{full_path}")

    @app.get("/healthz")
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok\n", headers=no_store)

    if static_path is not None:

        @app.get("/{full_path:path}")
        def static_bundle(full_path: str) -> FileResponse:
            path = static_path(full_path)
            if not path.exists():
                raise HTTPException(status_code=404, detail="static bundle not found")
            return FileResponse(path, headers=no_store)

    return app
