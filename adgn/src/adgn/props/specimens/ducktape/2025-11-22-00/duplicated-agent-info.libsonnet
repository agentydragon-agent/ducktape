local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The code has two problems in server.py:

    **Problem 1: Duplicated agent info construction**

    Both `list_agents()` and `get_agent_info()` build the same `AgentInfo` object with identical
    logic (determine run phase, check mode, build capabilities), but the implementation is
    duplicated line-by-line instead of extracting a shared helper (server.py, lines 252-302).

    **The correct approach:**
    Extract a `_build_agent_info(agent_id, agent)` helper method and call it from both resources.
    Alternatively, have `list_agents` call `get_agent_info` for each agent.

    **Problem 2: Thin wrapper methods**

    Methods `get_infrastructure()`, `get_agent_mode()`, and `get_local_runtime()` are trivial
    wrappers that just call `_get_agent_or_raise()` and access one field (server.py, lines 187-198).

    **The correct approach:**
    Let callers use `_get_agent_or_raise()` directly and access fields themselves
    (`agent.running`, `agent.mode`, `agent.local_runtime`). Or if public access is needed,
    rename `_get_agent_or_raise` to `get_agent` and let callers access fields directly.

    **Benefits:**
    1. Less code duplication (single agent info construction)
    2. Easier maintenance (one place for changes)
    3. Simpler API (fewer methods, clearer responsibilities)
    4. More direct (no unnecessary jumps between wrapper methods)
    5. Better testability (can test helper independently)

    **Why thin wrappers are harmful:**
    They add noise without meaningful abstraction, increase maintenance burden, and make it harder
    to see what's actually being accessed.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [252, 279],  // list_agents duplicates agent info construction
      [285, 302],  // get_agent_info has same logic
      [187, 198],  // Thin wrapper methods (get_infrastructure, get_agent_mode, get_local_runtime)
    ],
  },
)
