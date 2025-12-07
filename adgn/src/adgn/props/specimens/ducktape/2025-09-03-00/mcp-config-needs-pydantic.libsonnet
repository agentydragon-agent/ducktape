local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    MCP server configuration is handled using loose types (str | None for paths, Mapping[str, Any] for config objects) instead of proper Pydantic models. This loses the expected structure and forces type errors to be caught at runtime instead of at type-check time.

    Specific problems:
    - _load_mcp_config (lines 26-40) accepts str | None instead of Path | None, and returns untyped dict/list instead of validated Pydantic models
    - _LiveServer.__init__ (line 50) accepts cfg: Mapping[str, Any], but the config has clear expected structure: "command" (required string), "args" (optional list of strings), "env" (optional dict of string pairs)

    Using generic Mapping[str, Any] means:
    - Typos or missing keys are caught at runtime via KeyError
    - Readers must infer the shape from usage
    - No static type checking of config structure
    - Invalid values (wrong types) aren't caught until execution

    Define a Pydantic model that captures the expected shape:
      class McpServerConfig(BaseModel):
          command: str
          args: list[str] = Field(default_factory=list)
          env: dict[str, str] = Field(default_factory=dict)

    Then:
    - _load_mcp_config should accept Path | None, read YAML/JSON, and return validated McpServerConfig instances
    - _LiveServer.__init__ should accept cfg: McpServerConfig directly

    This makes the contract explicit, enables static type checking, and catches configuration errors early.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[26, 40], 50],
  },
)
