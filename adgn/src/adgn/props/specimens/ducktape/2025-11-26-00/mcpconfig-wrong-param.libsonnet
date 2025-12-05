local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Line 189 uses `MCPConfig(servers={})` but the correct parameter name is `mcpServers`,
    not `servers`. This creates an extra unwanted field in the config object.

    **The problem:** Pydantic accepts `servers` due to field aliasing or extra fields config,
    but it's not canonical. Result: `{'mcpServers': {}, 'servers': {}}` (two fields instead
    of one).

    Verified: `MCPConfig().model_dump()` produces `{'mcpServers': {}}`, but
    `MCPConfig(servers={}).model_dump()` produces `{'mcpServers': {}, 'servers': {}}`.

    **Fix:** Use `MCPConfig()` (since default is empty dict) or `MCPConfig(mcpServers={})`
    for explicitness. Removes extra field and matches the actual schema.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [189, 189],  // MCPConfig(servers={}) - wrong parameter
    ],
  },
)
