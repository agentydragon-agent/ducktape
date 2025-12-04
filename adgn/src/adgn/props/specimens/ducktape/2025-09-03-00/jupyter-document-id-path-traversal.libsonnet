local I = import '../../lib.libsonnet';

I.falsePositive(
  rationale=|||
    False positive: document_id is CLI-controlled (wrapper --document-id), not an MCP tool input.
    The value is used to create a notebook path under the configured workspace; this is an internal
    parameter under our control rather than an untrusted input.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [
      [37, 52],
      [480, 506],
    ],
  },
)
