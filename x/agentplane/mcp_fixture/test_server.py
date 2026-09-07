"""Exercise the deployed app shape with a real no-auth streamable-HTTP client."""

import httpx
import pytest_bazel
from fastmcp.client import Client
from mcp.types import TextContent

from util.net import pick_free_port
from util.testing.asgi import serve_app
from x.agentplane.mcp_fixture.server import create_server


async def test_streamable_http_contract() -> None:
    app = create_server().http_app(path="/mcp", stateless_http=True, json_response=True)
    port = pick_free_port()
    async with serve_app(app, port=port):
        url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient() as http:
            health = await http.get(f"{url}/healthz")
            assert health.status_code == 200
            assert health.text == "ok\n"
        # Fresh connections as well as repeated calls: no credential or retained session required.
        for _ in range(2):
            async with Client(f"{url}/mcp") as client:
                tools = await client.list_tools()
                assert [tool.name for tool in tools] == ["fixture_info"]
                assert tools[0].inputSchema.get("properties", {}) == {}
                annotations = tools[0].annotations
                assert annotations is not None
                assert annotations.readOnlyHint is True
                assert annotations.destructiveHint is False
                assert annotations.idempotentHint is True
                assert annotations.openWorldHint is False
                assert await client.list_resources() == []
                assert await client.list_prompts() == []
                for _ in range(2):
                    result = await client.call_tool("fixture_info", {})
                    assert result.is_error is False
                    assert result.content == [TextContent(type="text", text="agentplane-mcp0-ok")]


if __name__ == "__main__":
    pytest_bazel.main()
