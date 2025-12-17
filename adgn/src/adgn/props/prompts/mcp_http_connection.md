# MCP Server Connection via HTTP

An MCP server is available via Streamable HTTP transport.
Connection details are in environment variables:
- `MCP_SERVER_URL`: Full HTTP endpoint URL for the MCP server (including path, typically `/mcp`)
  - Example: `http://172.19.0.1:12345/mcp`
- `MCP_SERVER_TOKEN`: Bearer token for authentication

**IMPORTANT**: You must use Python with the MCP SDK to connect to the HTTP server. The `mcptools` CLI only supports stdio transport and will not work.

## Using Python MCP SDK (Required)

**Complete working example:**

```python
{% include 'examples/mcp_http_client_example.py' %}
```

Key steps:
1. Use `streamablehttp_client()` with bearer token auth
2. Call `session.initialize()` to get server instructions
3. Call `session.list_tools()` to inspect tool schemas
4. Call `session.call_tool(name, arguments)` to invoke tools

## Important

- **REQUIRED**: Connect to the server and follow server instructions from `init_result.instructions` for correct workflow
- **Inspect tool schemas**: Use `session.list_tools()` to get each tool's:
  - `name` - Tool identifier
  - `description` - What the tool does
  - `inputSchema` - JSON Schema defining parameter types, descriptions, constraints, and required fields
- **Respect the schema**: Read the `inputSchema` carefully to understand what parameters each tool accepts and their validation rules
- **Authentication**: Always include the `Authorization: Bearer $MCP_SERVER_TOKEN` header when creating the HTTP client
- **Need more details?**: Read the source code of the `mcp` package if you need more information about the API:
  - Find the package location: `python3 -c "import mcp; print(mcp.__file__)"`
  - Read relevant modules: `mcp.client.streamable_http`, `mcp.types`, etc.
- Server documentation is authoritative; follow it precisely
