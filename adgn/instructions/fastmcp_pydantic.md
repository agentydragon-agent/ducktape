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

- Programmatic: connect directly to your FastMCP server or a Compositor client and list tools
```python
# Quick check snippet (in-proc server)
import asyncio
from fastmcp.client import Client
from my_server import make_server  # returns a FastMCP("demo") instance

async def main():
    server = make_server()
    async with Client(server) as client:
        tools = await client.list_tools()
        for t in tools:
            if t.name == "done":
                # JSON Schema for the input model
                print(t.inputSchema)
asyncio.run(main())
```
- Manual: log/print the schema FastMCP emits (client.list_tools()), confirm:
  - type: "object"
  - properties include your fields (e.g., outcome, summary)
  - required matches your model (e.g., summary optional if default)
  - unions show as oneOf with discriminator

## Our wiring (FastMCP → OpenAI/Claude)
- We map MCP list_tools into OpenAI/Anthropic tool definitions:
  - name: <server>_<tool>
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

# FastMCP + Pydantic: Typed tool I/O (canonical patterns)

Scope
- How to define FastMCP tools with precise, validated inputs and stable, typed outputs
- When to use Pydantic TypeAdapter explicitly (rare)

Core rules
- Inputs: Prefer a single Pydantic BaseModel parameter for non‑trivial tools
  - FastMCP parses and validates the inbound dict against your model automatically
  - Use ConfigDict(extra="forbid") on models that must be strict
- Outputs: Return Pydantic models and discriminated unions for stable shapes
  - Object‑like returns (dict, BaseModel, dataclass) become structuredContent automatically
  - Use Annotated[..., Field(discriminator="kind")] for unions
- Don’t hand‑parse or re‑validate inside tools; FastMCP already does it for you
  - Manual TypeAdapter is only for ad‑hoc parsing outside FastMCP’s auto‑path (e.g., tests)

Minimal example (single BaseModel input + discriminated union output)
```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("editor")

class DoneInput(BaseModel):
    outcome: Literal["success", "failure"] = "success"
    summary: str = ""
    model_config = ConfigDict(extra="forbid")  # strict

class Success(BaseModel):
    kind: Literal["Success"] = "Success"
    summary: str

class Failure(BaseModel):
    kind: Literal["Failure"] = "Failure"
    summary: str

DoneResponse = Annotated[Success | Failure, Field(discriminator="kind")]

@mcp.tool()
def done(input: DoneInput) -> DoneResponse:
    # input is already a validated DoneInput (no TypeAdapter needed)
    if input.outcome == "success":
        return Success(summary=input.summary or "ok")
    return Failure(summary=input.summary or "aborted")
```

Testing and ad‑hoc parsing (TypeAdapter)
- Use TypeAdapter only when you need to parse a dict/JSON outside a tool (e.g., tests asserting server output):
```python
from pydantic import TypeAdapter
page = TypeAdapter(TextPage).validate_python(payload_dict)
# or
page = TypeAdapter(TextPage).validate_json(payload_json)
```
- Inside tools: do not call TypeAdapter; FastMCP validates parameters before your function runs, and serializes BaseModel returns to structuredContent.

Gotchas and best practices
- Unions must be discriminated to give clients a stable schema; prefer a single discriminator key like kind
- Output schemas must be objects (MCP constraint). Primitive returns are wrapped under {"result": ...} with x-fastmcp-wrap-result (FastMCP handles this)
- Keep models small and descriptive; add Field(..., description="...") to help the planner
- Use ConfigDict(extra="forbid") where strictness matters
- Return concrete models from tools; avoid mixing raw dicts and models for the same tool

When to introduce TypeAdapter in code
- Converting free‑form JSON (not bound to a tool) into a typed model
- Validating nested fragments returned from external APIs before further processing
- Tests that assert on structured payloads (e.g., DiffResult, TextPage) — prefer TypeAdapter over model_validate

Version notes
- Structured outputs and output schemas are supported in FastMCP ≥ 2.10
- FastMCP preserves Annotated metadata (include_extras=True), so discriminators are exported in JSON Schema

References
- FastMCP tools (Pydantic models, structured output, output schemas): https://gofastmcp.com/servers/tools
- Pydantic v2 TypeAdapter: https://docs.pydantic.dev/latest/usage/validators/#typeadapter
