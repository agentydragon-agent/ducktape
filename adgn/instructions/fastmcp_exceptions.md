# FastMCP tool exceptions and error handling

## TL;DR
- Don’t blanket-catch exceptions inside `@mcp.tool` — let FastMCP surface unexpected failures as MCP errors.
- Use typed, discriminated unions for expected OK/ERR flows; reserve ToolError for operational failures.
- Prefer strict, typed inputs (Pydantic) so FastMCP returns clear validation errors automatically.

## How FastMCP surfaces errors
- Tool exceptions are caught and returned as MCP errors (isError=true). The server stays healthy; inspect server logs for details.
- Successful calls return structured content (when you return Pydantic models/dicts/dataclasses) and traditional content blocks.
- For error results, structured content is typically absent; read the error text from content blocks.

## Best practices
- Validation first:
  - Define a single Pydantic BaseModel parameter per non‑trivial tool; add Field descriptions/constraints.
  - Use ConfigDict(extra="forbid") when shape must be strict.
- Expected failures (normal control flow):
  - Return a typed, discriminated union (stable JSON Schema for clients).
- Operational failures (I/O, environment, timeouts):
  - Raise fastmcp.exceptions.ToolError("message", code="...", details={...}).
  - Enable mask_error_details to avoid leaking internals; ToolError message passes through as user‑facing text.
- Keep tool bodies small; let the server boundary handle unexpected exceptions.

## Typed error payloads (normal control flow)
Use a discriminated union so clients get a stable, machine‑usable shape.

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("critic")

class Ok(BaseModel):
    kind: Literal["Ok"] = "Ok"
    result: str

class Err(BaseModel):
    kind: Literal["Err"] = "Err"
    message: str

Result = Annotated[Ok | Err, Field(discriminator="kind")]

@mcp.tool()
def check(path: str) -> Result:
    if path.endswith(".py"):
        return Ok(result="looks good")
    return Err(message="unsupported file type")
```

## Operational errors (raise ToolError)
Raise ToolError for failures where retry/diagnostics are appropriate.

```python
from mcp.server.fastmcp import FastMCP, ToolError

mcp = FastMCP("fetcher")

@mcp.tool()
def fetch(url: str) -> dict:
    try:
        resp = http_get(url, timeout=5)
    except TimeoutError as e:
        raise ToolError("timeout", code="TIMEOUT", details={"url": url}) from e
    if resp.status != 200:
        raise ToolError("bad status", code="HTTP", details={"status": resp.status})
    return {"ok": True, "body": resp.text}
```

## Client behavior
- Default: client.call_tool(...) raises ToolError on tool failure.
- With raise_on_error=False you receive a result object where result.is_error is True and content contains the error text.

## Lifespan
- Errors in lifespan (startup/shutdown) prevent successful initialize; clients see initialize failure. Diagnose via server logs.

## References
- Tools — validation, structured output, error handling: https://gofastmcp.com/servers/tools
- Clients — tool success/error envelopes: https://gofastmcp.com/clients/tools
- Exceptions reference (ToolError, ValidationError): https://gofastmcp.com/python-sdk/fastmcp-exceptions
- Server settings/logging: https://gofastmcp.com/servers/server
