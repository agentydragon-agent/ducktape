local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Comments reference historical code states or duplicate log messages/method names.

    Pattern 1 (compositor_factory.py:40, 45): "Mount...engine (now an MCP server)" references historical refactoring state irrelevant after completion.

    Pattern 2 (server.py:209, 237, 361, 363): "Notify that..." comments duplicate what method names/log messages already convey.

    Pattern 3 (server.py:416): Confusing middleware comment with "except... Actually, we want..." contradicts itself instead of stating what it does.

    These comments create maintenance burden and must be updated as code changes. Delete them; log messages and method names are sufficient.
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/compositor_factory.py': [40, 45],
      },
      note: 'Lines 40, 45: "Mount approval policy engine (now an MCP server)", "Mount approvals hub (now an MCP server)"',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/compositor_factory.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/mcp_bridge/server.py': [209, 237, 361, 363, 416, 429, 431, 441, 443],
      },
      note: 'Lines 209, 237, 361, 363: "Notify that..." comments; Line 416: Confusing auth comment with "Actually, we want..."; Lines 429, 431, 441, 443: Implementation detail comments',
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/server.py']],
    },
  ],
)
