local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The code has a comment claiming imports are placed inline "to avoid circular dependency
    with registry setup", but there is NO actual circular dependency.

    **Current implementation (app.py:179-182):**
    ```python
    # Create agents management server for MCP routing
    # Import here to avoid circular dependency with registry setup
    from adgn.agent.mcp_bridge.compositor_factory import create_global_compositor  # noqa: PLC0415
    from adgn.agent.mcp_bridge.server import InfrastructureRegistry  # noqa: PLC0415
    ```

    **Problem:**
    - The comment claims there's a circular dependency
    - Investigation shows mcp_bridge modules do NOT import from app.py
    - Therefore, no circular dependency exists
    - The imports can safely be moved to the top of the file

    **Verification:**
    ```bash
    grep -r "from adgn.agent.server.app import" adgn/src/adgn/agent/mcp_bridge/
    # Result: No imports from app.py found
    ```

    **Correct approach:**
    Move these imports to the top of the file with the other imports and delete the
    misleading comment:

    ```python
    from adgn.agent.mcp_bridge.compositor_factory import create_global_compositor
    from adgn.agent.mcp_bridge.server import InfrastructureRegistry
    ```

    **Benefits:**
    1. Standard import organization (all imports at top)
    2. No misleading comments about non-existent problems
    3. Easier to see all module dependencies
    4. No noqa comments needed (PLC0415 is for imports not at module level)

    **Note:** If there WAS a circular dependency, the correct fix would be to refactor
    the architecture to eliminate it, not hide it with inline imports.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [179, 182],  // Misleading circular dependency comment and inline imports
    ],
  },
)
