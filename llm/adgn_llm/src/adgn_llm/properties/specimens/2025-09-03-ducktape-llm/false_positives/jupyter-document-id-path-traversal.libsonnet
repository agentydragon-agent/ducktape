{
  rationale: |||
    False positive: document_id is CLI-controlled (wrapper --document-id), not an MCP tool input.
    The value is used to create a notebook path under the configured workspace; this is an internal
    parameter under our control rather than an untrusted input.
  |||,
  instances: [
    {
      files: {
        'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [
          { start_line: 37, end_line: 52 },
          { start_line: 480, end_line: 506 },
        ],
      },
    },
  ],
}
