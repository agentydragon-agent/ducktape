local I = import '../../specimens/lib.libsonnet';

// Merged: unnecessary-obvious-comments, unnecessary-outdated-comments
// Both describe comments that add no value (obvious or historical)

I.issueOneOccurrence(
  rationale= |||
    Multiple comments state obvious facts or reference outdated implementation details,
    adding no value to code understanding.

    **Pattern 1: Comments stating the obvious** (approvals.py):
    ```python
    # Call persistence to get ACTUAL ID
    policy_id = await self._persistence.set_policy(...)

    # Create proposal and get actual database-assigned ID
    proposal_id = await self._persistence.create_policy_proposal(...)
    ```

    Problems:
    - Obviously calling persistence (it's right there in the code)
    - Obviously getting actual IDs (method names and types make this clear)
    - Comments just restate what's visually apparent
    - If clarification is needed, should explain WHY, not WHAT

    **Pattern 2: Historical "now an MCP server" comments** (compositor_factory.py, server.py):
    ```python
    # Mount approval policy engine (now an MCP server)
    await comp.mount_inproc("policy", infra.approval_engine)
    logger.info(f"Mounted approval policy engine for agent {agent_id}")

    # Notify that agent list changed
    await self.notify_agents_list_changed()
    ```

    Problems:
    - "now an MCP server" is historical commentary about past code state
    - Irrelevant now that refactoring is complete
    - Comment duplicates what the log message says
    - Method name already says what it does

    **Pattern 3: Confusing/obvious auth comments** (server.py):
    ```python
    # Add UI token authentication (applies to all routes except /mcp which has its own auth)
    # Actually, we want auth on /mcp too, so add middleware
    app.add_middleware(UITokenAuthMiddleware, expected_token=ui_token)

    # Generate or use provided UI token
    if ui_token is None:
        ui_token = generate_ui_token()
    ```

    Problems:
    - Confused language: "except... Actually, we want..." - just say what it does
    - Code is self-explanatory for the second example

    **Why these are problematic:**
    - **Noise**: Make code harder to scan without providing information
    - **Outdated**: Historical references become confusing over time
    - **Redundant**: Log messages and method names already convey information
    - **Maintenance burden**: Must be updated as code changes

    **Recommended fix:**
    Delete these comments. Method names, log messages, and code structure are sufficient.
    If clarification is needed, explain WHY operations are performed, not WHAT they do.

    **Benefits:**
    - Cleaner, more maintainable code
    - No outdated historical references
    - Focus on non-obvious information
    - Follows principle: comments should explain WHY, not WHAT
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      319,  // "Call persistence to get ACTUAL ID"
      346,  // "Create proposal and get actual database-assigned ID"
    ],
    'adgn/src/adgn/agent/mcp_bridge/compositor_factory.py': [
      40,   // "Mount approval policy engine (now an MCP server)"
      45,   // "Mount approvals hub (now an MCP server)"
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      209,  // "Notify that..." comment
      237,  // "Notify that..." comment
      361,  // "Notify that..." comment
      363,  // "Notify that..." comment
      416,  // Confusing auth comment
      421,  // "Generate or use provided UI token"
      429,  // "The compositor (FastMCP) is itself an ASGI app"
      431,  // Implementation detail comment
      441,  // "Notify that..." comment
      443,  // "Notify that..." comment
      459,  // "Health check endpoint" (should be docstring if needed)
    ],
  },
)
