from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict

from .config import PilotSettings, load_settings
from .runtime import PilotRuntime

logger = logging.getLogger(__name__)


class RestartRequest(BaseModel):
    reason: str | None = None
    model_config = ConfigDict(extra="forbid")


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model_config = ConfigDict(extra="forbid")


class RestartResponse(BaseModel):
    status: Literal["restarted"]
    reason: str
    model_config = ConfigDict(extra="forbid")


class ShutdownResponse(BaseModel):
    status: Literal["shutting_down"]
    model_config = ConfigDict(extra="forbid")


@lru_cache(maxsize=1)
def _settings() -> PilotSettings:
    settings = load_settings()
    if not settings.matrix.configured:
        raise RuntimeError("Matrix settings incomplete; set MATRIX_BASE_URL and MATRIX_ACCESS_TOKEN")
    return settings


def create_app(settings: PilotSettings | None = None) -> FastAPI:
    settings = settings or _settings()
    runtime = PilotRuntime(settings)

    app = FastAPI(title="Ember", version="0.0.1")

    @app.on_event("startup")
    async def _startup() -> None:
        await runtime.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await runtime.stop()

    @app.get("/healthz")
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    async def _get_runtime() -> PilotRuntime:
        return runtime

    @app.post("/control/restart")
    async def control_restart(
        request: RestartRequest, runtime_dep: PilotRuntime = Depends(_get_runtime)
    ) -> RestartResponse:
        await runtime_dep.restart()
        return RestartResponse(status="restarted", reason=request.reason or "")

    @app.post("/control/shutdown")
    async def control_shutdown(
        runtime_dep: PilotRuntime = Depends(_get_runtime),
    ) -> ShutdownResponse:
        await runtime_dep.stop()
        return ShutdownResponse(status="shutting_down")

    return app
