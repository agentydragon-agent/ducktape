"""No-auth, no-I/O MCP origin for staging transport acceptance."""

import asyncio

import uvicorn
from fastmcp.server import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import PlainTextResponse


def create_server() -> FastMCP:
    server = FastMCP("agentplane-mcp-fixture")

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    )
    def fixture_info() -> str:
        """Return the fixed MCP0 acceptance marker; takes no input and performs no I/O."""
        return "agentplane-mcp0-ok"

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok\n")

    return server


async def main() -> None:
    app = create_server().http_app(path="/mcp", stateless_http=True, json_response=True)
    await uvicorn.Server(
        uvicorn.Config(
            app, host="0.0.0.0", port=8080, limit_concurrency=16, timeout_keep_alive=5, timeout_graceful_shutdown=5
        )
    ).serve()


if __name__ == "__main__":
    asyncio.run(main())
