local I = import '../../lib.libsonnet';

// iss-038: McpState, PolicyState, and pending_approvals redundant with 2-layer compositor

I.issue(
  rationale= |||
    `McpState`, `PolicyState`, and `pending_approvals` in `AgentStatusCore` duplicate
    information available via the 2-layer compositor exposing MCP server state.

    **Problem: Thin wrappers duplicating compositor resources**

    | Field | Type | Lines | Issue |
    |-------|------|-------|-------|
    | `mcp` | `McpState` | 76-78 | Wraps `dict[str, ServerEntry]`, no behavior |
    | `policy` | `PolicyState` | 66-68 | Wraps nullable int, no behavior |
    | `pending_approvals` | `int` | 91 | Duplicates approval policy server data |

    **Impact:**
    - Type indirection (must access `.entries` for data)
    - Manual state tracking instead of querying compositor
    - Sync issues between custom status and MCP resources
    - Redundant APIs (custom status vs MCP protocol)

    **With 2-layer compositor, this data is available via resources:**

    | Custom field | MCP resource |
    |--------------|--------------|
    | `mcp: McpState` | `resources://compositor/servers` |
    | `policy: PolicyState` | `resources://approval-policy/policy.py` |
    | `pending_approvals: int` | `resources://approval-policy/pending` (compute `len()`) |

    **Solution: Remove redundant fields**

    ```python
    class AgentStatusCore(BaseModel):
        id: str
        live: bool
        active_run_id: UUID | None
        lifecycle: AgentLifecycle
        run_phase: RunPhase
        container: ContainerState
        # Removed: policy, mcp, pending_approvals (all via MCP resources)
    ```

    Clients query MCP resources directly:
    ```python
    servers = await client.resources.read("resources://compositor/servers")
    policy = await client.resources.read("resources://approval-policy/policy.py")
    pending = await client.resources.read("resources://approval-policy/pending")
    count = len(pending)
    ```

    **Benefits:**
    - Single source of truth (MCP resources authoritative)
    - Automatic updates (resource subscriptions)
    - Consistent interface (all state via MCP)
    - Simpler status model (only non-MCP state)

    **What remains:** Only state not naturally available via MCP resources (agent ID,
    lifecycle, container state, etc.).

    **Principle:** Don't duplicate MCP-available data in custom APIs. Let clients use
    standard MCP protocol to avoid sync issues.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/status_shared.py': [
      [66, 68],   // PolicyState thin wrapper
      [76, 78],   // McpState thin wrapper
      [91, 91],   // pending_approvals redundant field
    ],
  },
)
