local I = import '../../specimens/lib.libsonnet';

// iss-038: McpState, PolicyState, and pending_approvals redundant with 2-layer compositor

I.issueOneOccurrence(
  rationale= |||
    The `McpState`, `PolicyState` thin wrappers and `pending_approvals` integer field
    in `AgentStatusCore` duplicate information that should now be available via the
    2-layer compositor exposing MCP server state natively to the frontend.

    **Problem 1: McpState is a thin wrapper that should be replaced**

    `McpState` wraps a `dict[str, ServerEntry]` with no additional behavior, making it
    an unnecessary type wrapper.

    **Current implementation (status_shared.py, lines 76-78):**
    ```python
    class McpState(BaseModel):
        entries: dict[str, ServerEntry]
        model_config = ConfigDict(extra="forbid")
    ```

    **Why this is problematic:**

    1. **Thin wrapper with no value**: Just wraps a dict, adds no validation or behavior
    2. **Type indirection**: Must access `.entries` to get the actual data
    3. **Redundant with compositor**: MCP server state should come from compositor resources
    4. **Manual state tracking**: Code must maintain this dict instead of querying compositor

    **The correct approach:**

    With the 2-layer compositor architecture, MCP server state is available as resources:
    - `resources://compositor/servers` - list of mounted servers
    - `resources://compositor/servers/<name>` - individual server state
    - These resources are automatically updated when servers mount/unmount

    Remove `McpState` entirely and query compositor resources:
    ```python
    # Old:
    class AgentStatusCore(BaseModel):
        mcp: McpState  # Manual tracking

    # New:
    class AgentStatusCore(BaseModel):
        # MCP state available via compositor resources, no field needed
        pass

    # Clients read MCP state from resources:
    servers = await client.resources.read("resources://compositor/servers")
    ```

    **Problem 2: PolicyState is similarly thin**

    `PolicyState` wraps a nullable integer with no additional meaning:

    **Current implementation (status_shared.py, lines 66-68):**
    ```python
    class PolicyState(BaseModel):
        id: int | None = None
        model_config = ConfigDict(extra="forbid")
    ```

    This should also be available via MCP:
    - `resources://approval-policy/policy.py` - active policy source
    - `resources://approval-policy/proposals` - pending proposals

    **Problem 3: pending_approvals count is redundant**

    `AgentStatusCore` has a `pending_approvals: int` field that duplicates information
    available from the approval policy server.

    **Current implementation (status_shared.py, lines 82-91):**
    ```python
    class AgentStatusCore(BaseModel):
        id: str
        live: bool
        active_run_id: UUID | None
        lifecycle: AgentLifecycle
        run_phase: RunPhase
        policy: PolicyState
        ui: UiStateLite
        mcp: McpState
        container: ContainerState
        pending_approvals: int  # ← Redundant
    ```

    **Why this is redundant:**

    With approval policy as an MCP server, pending approvals are available via:
    - `resources://approval-policy/pending` (list of pending approval requests)
    - Or via `approval-policy.list_pending_approvals` tool

    The count can be computed client-side from the resource list.

    **The correct approach for all three:**

    Remove these fields from `AgentStatusCore` and make the data available via MCP:

    ```python
    class AgentStatusCore(BaseModel):
        id: str
        live: bool
        active_run_id: UUID | None
        lifecycle: AgentLifecycle
        run_phase: RunPhase
        container: ContainerState
        # Removed: policy, mcp, pending_approvals - all available via MCP

        model_config = ConfigDict(extra="forbid")
    ```

    Clients query MCP resources for this information:
    ```python
    # MCP servers:
    servers = await client.resources.read("resources://compositor/servers")

    # Policy state:
    policy = await client.resources.read("resources://approval-policy/policy.py")

    # Pending approvals:
    pending = await client.resources.read("resources://approval-policy/pending")
    count = len(pending)
    ```

    **Benefits:**

    1. **Single source of truth**: MCP resources are authoritative
    2. **Automatic updates**: Resource subscriptions provide change notifications
    3. **Consistent interface**: All state via MCP protocol
    4. **Reduced duplication**: No manual state tracking
    5. **Simpler status model**: Only non-MCP state in `AgentStatusCore`

    **What should remain in AgentStatusCore:**

    Only state that isn't naturally available via MCP resources:
    - `id`: Agent identifier
    - `live`: Whether agent runtime is running
    - `active_run_id`: Current run ID (though this could be a resource too)
    - `lifecycle`: Agent lifecycle state (STARTING/READY/STOPPING)
    - `run_phase`: Current execution phase
    - `container`: Runtime container state

    Everything related to MCP servers, policies, or approvals should come from MCP.

    **Migration path:**

    1. Verify 2-layer compositor exposes these resources:
       - `resources://compositor/servers`
       - `resources://approval-policy/policy.py`
       - `resources://approval-policy/pending`
    2. Update UI/clients to read from resources instead of status fields
    3. Remove `mcp`, `policy`, `pending_approvals` from `AgentStatusCore`
    4. Delete `McpState` and `PolicyState` types

    **Why this duplication happened:**

    These fields likely predate the 2-layer compositor architecture. When MCP servers
    weren't user-facing, status had to manually expose this information. Now that the
    compositor makes MCP resources accessible, the duplication is unnecessary.

    **Design principle: Don't duplicate MCP-available data in custom APIs**

    If information is available via MCP resources/tools:
    - Don't create parallel REST/WS endpoints
    - Don't embed it in custom status models
    - Let clients use standard MCP protocol

    This keeps the architecture consistent and avoids synchronization issues.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/status_shared.py': [
      [66, 68],   // PolicyState thin wrapper
      [76, 78],   // McpState thin wrapper
      [91, 91],   // pending_approvals redundant field
    ],
  },
)
