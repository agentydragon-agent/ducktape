local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Docker Exec MCP tool inputs should be declared as strongly-typed (Pydantic) parameters on the FastMCP
    tool function, so validation is handled by the framework and schemas are auto-exported to MCP clients.

    Current pattern (manual dict/field extraction in call_tool) leads to ad-hoc checks and coercions.

    FastMCP-idiomatic pattern (two options):
    - Single Pydantic payload model:
        @app.tool()
        async def docker_exec(payload: ExecInputs) -> ExecResultPayload: ...
      where ExecInputs is a Pydantic BaseModel with strict field types.
    - Separate strongly-typed parameters:
        @app.tool()
        async def docker_exec(cmd: list[str], timeout_secs: float | None = None, ...) -> ExecResultPayload: ...

    Required input typing (minimum):
    - cmd: list[str] (non-empty)
    - cwd: str | None
    - env: dict[str, str] | None (values must be strings; reject non-strings)
    - user: str | None
    - tty: bool (no truthy-string coercion)
    - shell: bool (no truthy-string coercion)
    - timeout_secs: float | None (>= 0; no string coercion)

    Benefits:
    - Validation moves to FastMCP/Pydantic; no manual coercion.
    - JSON Schema for the tool is generated directly from the Pydantic model and visible to MCP clients.
    - Clear, self-documenting contracts; fewer runtime surprises.

    Acceptance criteria:
    - Define a Pydantic BaseModel ExecInputs with the fields above (strict types; min_items=1 for cmd).
    - Change the FastMCP registration to use a typed tool signature (either payload model or per-arg types).
    - Remove manual extraction/coercion in call_tool; rely on Pydantic validation (any invalid inputs must raise).
    - Keep existing shell/timeout composition logic, but operate only on already-validated, correctly-typed values.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py': [[200, 250], [88, 112]],
  },
)
