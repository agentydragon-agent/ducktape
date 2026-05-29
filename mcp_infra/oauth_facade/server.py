"""HTTP entrypoint for the generic Authentik-backed MCP OAuth facade."""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_infra.authentik_auth.auth import build_authentik_auth
from mcp_infra.oauth_facade.config import FacadeSettings
from mcp_infra.oauth_facade.proxy import build_proxy_server
from mcp_infra.persistence import build_client_storage

logger = logging.getLogger(__name__)


def build_server(settings: FacadeSettings, *, auth_provider: Any | None = None) -> tuple[Any, Any]:
    """Build the facade FastMCP server. `auth_provider` is injectable for tests.

    Returns `(server, client_storage)` so the caller can pre-warm the storage
    in the ASGI lifespan — without this the GLIDE client's first connect
    (~400ms cold) can exceed the per-request timeout on the very first OAuth
    callback, surfacing as `glide_shared.exceptions.TimeoutError: timed out`.
    """
    client_storage = build_client_storage(settings.persistence)
    auth = (
        auth_provider
        if auth_provider is not None
        else build_authentik_auth(settings.auth, client_storage=client_storage)
    )
    return build_proxy_server(settings, auth=auth), client_storage


def create_app(settings: FacadeSettings, *, auth_provider: Any | None = None) -> Starlette:
    server, client_storage = build_server(settings, auth_provider=auth_provider)
    mcp_app = server.http_app(path="/mcp")

    async def healthz(request) -> JSONResponse:
        return JSONResponse({"ok": True})

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if client_storage is not None and hasattr(client_storage, "setup"):
            await client_storage.setup()
            logger.info("client_storage pre-warmed (no lazy first-request init)")
        async with mcp_app.lifespan(app):
            yield

    return Starlette(routes=[Route("/healthz", healthz), Mount("/", app=mcp_app)], lifespan=lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    settings = FacadeSettings()
    app = create_app(settings)
    logger.info("%s listening on %s:%d", settings.facade_name, settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
