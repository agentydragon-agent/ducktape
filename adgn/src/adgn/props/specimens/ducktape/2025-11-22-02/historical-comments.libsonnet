local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Comments reference historical code states or duplicates log messages.

    Pattern 1: "now an MCP server" comments:
    ```python
    # Mount approval policy engine (now an MCP server)
    await comp.mount_inproc("policy", infra.approval_engine)
    logger.info(f"Mounted approval policy engine for agent {agent_id}")
    ```

    Pattern 2: "Notify that..." comments duplicating log messages:
    ```python
    # Notify that agent list changed
    await self.notify_agents_list_changed()
    ```

    Pattern 3: Confusing middleware comments:
    ```python
    # Add UI token authentication (applies to all routes except /mcp which has its own auth)
    # Actually, we want auth on /mcp too, so add middleware
    app.add_middleware(UITokenAuthMiddleware, expected_token=ui_token)
    ```

    Problems:
    - Historical references ("now an MCP server") are irrelevant after refactoring is complete
    - Comments duplicate what log messages or method names already convey
    - Confused language ("except... Actually, we want...") should just state what it does
    - Maintenance burden: must be updated as code changes

    Delete these comments. Log messages and method names are sufficient.
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
