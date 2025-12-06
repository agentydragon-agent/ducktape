# MCP Server Connection via HTTP

An MCP server is available via Streamable HTTP transport.
Connection details are in environment variables:
- `MCP_SERVER_URL`: Full HTTP endpoint URL for the MCP server (including path, typically `/mcp`)
  - Example: `http://172.19.0.1:12345/mcp`
- `MCP_SERVER_TOKEN`: Bearer token for authentication

**IMPORTANT**: You must use Python with the MCP SDK to connect to the HTTP server. The `mcptools` CLI only supports stdio transport and will not work.

## Using Python MCP SDK (Required)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
import os

async with streamablehttp_client(
    os.getenv('MCP_SERVER_URL'),
    headers={"Authorization": f"Bearer {os.getenv('MCP_SERVER_TOKEN')}"}
) as (read, write, _), \
           ClientSession(read, write) as session:
    # 1. Initialize - get server info and instructions
    init_result = await session.initialize()
    print(init_result.instructions)

    # 2. List available tools - inspect their schemas
    tools = await session.list_tools()
    for tool in tools:
        print(f"\nTool: {tool.name}")
        print(f"Description: {tool.description}")
        print(f"Input Schema: {tool.inputSchema}")

    # 3. Call tools as needed
    result = await session.call_tool("tool_name", arguments={...})
```

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
