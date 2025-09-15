# FastMCP tool exceptions and error handling

## TL;DR
- Do not blanket-catch exceptions inside @mcp.tool. Let FastMCP handle unexpected exceptions.
- For expected, user-facing failures, raise ToolError with a safe message.
- Prefer Pydantic validation (typed inputs) to fail fast with informative errors.

## How FastMCP surfaces errors
- Tool exceptions are caught by FastMCP and returned as MCP errors (isError=true). The server remains running; the transport stays healthy.
- Successful calls return structured content (structured JSON when you return Pydantic models) and traditional content blocks. Error calls carry text content describing the failure.

## Best practices
- Don’t catch Exception just to wrap an {ok: False}. It hides useful traces and bypasses the protocol’s error channel.
- Raise fastmcp.exceptions.ToolError for predictable, user-visible errors (e.g., bad user input, denied scope). This message is passed through even when error detail masking is enabled.
- Use Pydantic inputs with Field descriptions and constraints. FastMCP will validate parameters and return clear validation errors automatically.
- Keep tool bodies small and let the outer server boundary handle unexpected failures (crash-only philosophy inside a tool; process does not crash).

## Client behavior
- call_tool() raises ToolError by default if the tool failed. Use raise_on_error=False to receive a result object where result.is_error is True and content contains the error text.
- structured_content is typically absent for error results; read error text from content blocks.

## Lifespan
- Errors in lifespan (startup/shutdown) prevent successful server initialization; clients see initialize failures. Use server logs to debug.

## References
- Tools — error handling, validation, structured content: https://gofastmcp.com/servers/tools
- Client tool operations — success/error envelopes: https://gofastmcp.com/clients/tools
- Exceptions reference (ToolError, ValidationError): https://gofastmcp.com/python-sdk/fastmcp-exceptions
- Server settings/logging: https://gofastmcp.com/servers/server

## Minimal example

Server:
```python
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP("ErrDemo")

@mcp.tool()
def explode(kind: str) -> dict[str, str]:
    if kind == "value":
        raise ValueError("Bad value X")   # unexpected → MCP error
    if kind == "tool":
        raise ToolError("User-facing error message")  # expected → exposed message
    return {"ok": "true"}
```

Client:
```python
import asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

async def main():
    async with Client("http://localhost:8000/mcp") as c:
        try:
            await c.call_tool("explode", {"kind": "value"})
        except ToolError as e:
            print("raised:", e)
        r = await c.call_tool("explode", {"kind": "value"}, raise_on_error=False)
        print("is_error:", r.is_error, "text:", r.content[0].text)

asyncio.run(main())
```
