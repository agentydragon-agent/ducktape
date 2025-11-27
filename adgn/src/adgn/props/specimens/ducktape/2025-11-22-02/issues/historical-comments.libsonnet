local I = import '../../specimens/lib.libsonnet';

I.issueOccurrencesFromLines(
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
  linesByFile={
    'adgn/src/adgn/agent/mcp_bridge/compositor_factory.py': [
      40,  // "Mount approval policy engine (now an MCP server)"
      45,  // "Mount approvals hub (now an MCP server)"
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      209,  // "Notify that..." comment
      237,  // "Notify that..." comment
      361,  // "Notify that..." comment
      363,  // "Notify that..." comment
      416,  // Confusing auth comment with "Actually, we want..."
      429,  // "The compositor (FastMCP) is itself an ASGI app"
      431,  // Implementation detail comment
      441,  // "Notify that..." comment
      443,  // "Notify that..." comment
    ],
  },
)
