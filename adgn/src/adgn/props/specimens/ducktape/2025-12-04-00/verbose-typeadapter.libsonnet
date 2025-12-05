local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Using TypeAdapter wrapper unnecessarily for Pydantic model validation. Pydantic BaseModel classes have model_validate_json() class method that is more direct and idiomatic.

    Current: TypeAdapter(mcp_types.CallToolResult).validate_json(item.output)

    Better: mcp_types.CallToolResult.model_validate_json(item.output)
  |||,
  filesToRanges={'adgn/src/adgn/agent/agent.py': [554]},
)
