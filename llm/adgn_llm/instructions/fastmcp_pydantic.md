# FastMCP tool schemas (Pydantic)

## Why this matters
- LLMs plan tool calls from the advertised JSON Schema; correct schemas make calls reliable and remove the need to restate parameter shapes in prompt prose.
- Our adapters surface FastMCP tool schemas directly to the model as OpenAI/Anthropic tool definitions.

## Canonical pattern (use this by default)
- One tool parameter: a Pydantic BaseModel. Avoid dict[str, Any] or untyped params.
- Rich types: use Literal, Optional, enums, nested BaseModels, Annotated + Field for descriptions/constraints.
- Unions: make them discriminated with Field(discriminator="type") and tag each variant with a Literal value.
- Return value: it’s okay to return a Pydantic model (e.g., Success|Failure). Some clients ignore output schemas, but keeping it typed helps our tests and in‑proc use.

```python
from typing import Literal, Annotated
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")

class DoneInput(BaseModel):
    outcome: Literal["success", "failure"] = "success"
    summary: str = ""

class Success(BaseModel):
    type: Literal["Success"]
    summary: str

class Failure(BaseModel):
    type: Literal["Failure"]
    summary: str

DoneResult = Annotated[Success | Failure, Field(discriminator="type")]

@mcp.tool()
def done(payload: DoneInput) -> DoneResult:
    return Failure(type="Failure", summary="aborted")
```

## DOs
- Annotate every parameter precisely; prefer a single BaseModel argument for complex tools
- Use Field(..., description=...) to help the planner
- Use Literal/enums for closed sets; Optional[T] for nullable
- Use discriminated unions for Union[...] (Field(discriminator="type")).
- Keep models small and descriptive; nest when needed

## DON’Ts (these degrade/break schema)
- No dict[str, Any], Any, *args/**kwargs, or untyped params
- Don’t use dataclasses as input (wrap in a BaseModel)
- Don’t use bare Union without a discriminator when variants overlap
- Don’t restate the schema in prose; rely on the JSON Schema

## Verification (check the schema seen by the agent)
- Programmatic: use McpManager to list tools and inspect parameters
```python
# Quick check snippet
import asyncio
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from my_server import make_server  # returns a FastMCP instance

async def main():
    spec = make_inproc_slot_spec(make_server())
    async with McpManager({"demo": spec}) as m:
        tools = await m.list_tools(["demo"])
        for t in tools:
            if t["name"].endswith("__done"):
                print(t["name"], t["parameters"])  # should match DoneInput
asyncio.run(main())
```
- Manual: log/print the schema FastMCP emits (client.list_tools()), confirm:
  - type: "object"
  - properties include your fields (e.g., outcome, summary)
  - required matches your model (e.g., summary optional if default)
  - unions show as oneOf with discriminator

## Our wiring (FastMCP → OpenAI/Claude)
- We map MCP list_tools into OpenAI/Anthropic tool definitions:
  - name: mcp__<server>__<tool>
  - description: FastMCP tool description
  - parameters: inputSchema as returned by FastMCP (JSON Schema)
- If your tool is correctly typed, the model sees the exact parameter schema and can call it without extra prompt instructions.

## Common pitfalls and fixes
- Multiple positional params with missing annotations → add full typing or consolidate into a BaseModel
- Union without discriminator where variants overlap → add Field(discriminator="type") and tag each variant with a Literal
- Using Any or dict[str, Any] → replace with concrete types/BaseModels
- Extra forbid/allow mismatches → ensure model_config aligns with what the caller sends

## Notes
- Output schemas are not always consumed by clients; still return typed models to enforce structure in tests and in‑proc flows.
