# MCP Server Connection via HTTP

An MCP server is available via Streamable HTTP transport. Connection environment variables:
- `MCP_SERVER_URL`: HTTP endpoint URL for the MCP server. Example: `http://172.19.0.1:12345/mcp`
- `MCP_SERVER_TOKEN`: Bearer token for authentication

## Using Python MCP SDK

One way to connect to the server is using the Python MCP SDK (`mcp` package).
See `props_agent_util.examples.mcp_use` for an example (`python -c "from props_agent_util.examples import mcp_use; print(mcp_use.__file__)"`).

Key steps:
1. Create `StreamableHttpTransport` with bearer token auth header
2. Use `Client(transport)` async context manager to connect
3. **REQUIRED**: Follow server documentation from `init_result.instructions`.
   **Inspect tool schemas**: Use `session.list_tools()` to get each tool's `name`, `description` and `inputSchema`
4. Call `client.call_tool(name, arguments)` to invoke tools

Read source code of the `mcp` package if you need more information about the API (see `mcp.__file__`)
