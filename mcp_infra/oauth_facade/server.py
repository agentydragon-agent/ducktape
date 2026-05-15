"""HTTP entrypoint for the generic Authentik-backed MCP OAuth facade."""

from __future__ import annotations

import logging
import sys
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


def build_server(settings: FacadeSettings, *, auth_provider: Any | None = None):
    """Build the facade FastMCP server. `auth_provider` is injectable for tests."""
    client_storage = build_client_storage(settings.persistence)
    auth = (
        auth_provider
        if auth_provider is not None
        else build_authentik_auth(settings.auth, client_storage=client_storage)
    )
    return build_proxy_server(settings, auth=auth)


def create_app(settings: FacadeSettings, *, auth_provider: Any | None = None) -> Starlette:
    server = build_server(settings, auth_provider=auth_provider)
    mcp_app = server.http_app(path="/mcp")

    async def healthz(request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return Starlette(routes=[Route("/healthz", healthz), Mount("/", app=mcp_app)], lifespan=mcp_app.lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    settings = FacadeSettings()
    app = create_app(settings)
    logger.info("%s listening on %s:%d", settings.facade_name, settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
