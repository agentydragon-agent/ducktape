"""HTTP entrypoint for the Tana MCP OAuth facade."""

from __future__ import annotations

import logging
import sys
from typing import Any

import uvicorn
from fastmcp import Client
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_infra.authentik_auth.auth import build_authentik_auth
from tana.mcp_facade.config import ServerSettings
from tana.mcp_facade.proxy import build_proxy_server

logger = logging.getLogger(__name__)


def build_server(settings: ServerSettings, *, auth_provider: Any | None = None):
    """Build the facade server.

    `auth_provider` is injectable for tests so they can bypass OIDC discovery.
    """
    auth = auth_provider if auth_provider is not None else build_authentik_auth(settings.auth)
    return build_proxy_server(settings, auth=auth)


def create_app(settings: ServerSettings, *, auth_provider: Any | None = None) -> Starlette:
    server = build_server(settings, auth_provider=auth_provider)
    mcp_app = server.http_app(path="/mcp")

    async def healthz(request) -> JSONResponse:
        ok = True
        try:
            async with Client(settings.downstream_url, auth=settings.static_bearer_token) as client:
                await client.list_tools()
        except Exception:
            ok = False
        return JSONResponse({"ok": ok}, status_code=200 if ok else 503)

    return Starlette(routes=[Route("/healthz", healthz), Mount("/", app=mcp_app)], lifespan=mcp_app.lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    settings = ServerSettings()
    app = create_app(settings)
    logger.info("tana-mcp-facade listening on %s:%d", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
