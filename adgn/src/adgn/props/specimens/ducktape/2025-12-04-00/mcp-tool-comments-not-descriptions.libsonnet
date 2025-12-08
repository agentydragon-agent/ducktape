local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    MCP tool input model fields have comments containing agent-useful information, but these comments are invisible to the MCP client. SandboxExecArgs is an MCP tool input model (used by sandbox_exec tool on line 93), so field documentation that helps agents understand usage should be in Field(description="...") rather than comments.

    This matters because:
    1. Field descriptions are included in the JSON Schema sent to MCP clients
    2. LLM agents see Field descriptions when planning tool calls
    3. Comments are invisible to the MCP protocol and don't help the agent understand usage
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/mcp/exec/seatbelt.py': [[47, 48]]},
      note: 'Comment "Stateless: require a full policy on every call" describes policy field behavior but is invisible to MCP clients',
      expect_caught_from: [['adgn/src/adgn/mcp/exec/seatbelt.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/exec/seatbelt.py': [[52, 53]]},
      note: 'Comment "Explicit env to set/override in the child (applied after policy.env passthrough base)" explains env field semantics but is invisible to MCP clients',
      expect_caught_from: [['adgn/src/adgn/mcp/exec/seatbelt.py']],
    },
  ],
)
