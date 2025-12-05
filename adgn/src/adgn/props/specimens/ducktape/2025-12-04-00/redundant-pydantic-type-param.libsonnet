local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 133 in agent.py explicitly sets `type="text"` when constructing a TextContent object:
    `mcp_types.TextContent(type="text", text=message)`. This parameter is redundant if "text" is the
    default value for the type discriminator field. The construction should omit the type parameter
    unless it's required by the Pydantic model definition (i.e., has no default).
  |||,
  filesToRanges={'adgn/src/adgn/agent/agent.py': [133]},
)
