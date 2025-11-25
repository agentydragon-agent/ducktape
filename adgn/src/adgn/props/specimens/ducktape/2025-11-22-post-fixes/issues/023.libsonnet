local I = import '../../specimens/lib.libsonnet';

// iss-023: Unmounted resource URIs in resources.py

I.issueOneOccurrence(
  rationale= |||
    The `resources.py` module defines many parameterized resource URI helper functions
    (e.g., `agent_state()`, `agent_snapshot()`, `agent_mcp_state()`) that construct URIs
    like `resource://agents/{agent_id}/state`, but these URIs are never actually mounted
    as resources in the MCP server. Only `resource://agents/list` and
    `resource://agents/{agent_id}/info` are implemented.

    **Current implementation (resources.py, lines 16-67):**
    ```python
    def agent_state(agent_id: AgentID) -> str:
        """Resource URI for agent sampling state."""
        return f"resource://agents/{agent_id}/state"

    def agent_snapshot(agent_id: AgentID) -> str:
        """Resource URI for full compositor sampling snapshot."""
        return f"resource://agents/{agent_id}/snapshot"

    def agent_mcp_state(agent_id: AgentID) -> str:
        """Resource URI for MCP servers state."""
        return f"resource://agents/{agent_id}/mcp/state"

    def agent_approvals_pending(agent_id: AgentID) -> str:
        """Resource URI for pending approvals for an agent."""
        return f"resource://agents/{agent_id}/approvals/pending"

    def agent_approvals_history(agent_id: AgentID) -> str:
        """Resource URI for approval history timeline."""
        return f"resource://agents/{agent_id}/approvals/history"

    def agent_approval(agent_id: AgentID, call_id: str) -> str:
        """Resource URI for a specific approval."""
        return f"resource://agents/{agent_id}/approvals/{call_id}"

    def agent_policy_proposals(agent_id: AgentID) -> str:
        """Resource URI for policy proposals."""
        return f"resource://agents/{agent_id}/policy/proposals"

    def agent_policy_state(agent_id: AgentID) -> str:
        """Resource URI for policy state (active policy + proposals)."""
        return f"resource://agents/{agent_id}/policy/state"

    def agent_session_state(agent_id: AgentID) -> str:
        """Resource URI for agent session state and transcript."""
        return f"resource://agents/{agent_id}/session/state"

    def agent_ui_state(agent_id: AgentID) -> str:
        """Resource URI for UI state (only if UI server attached)."""
        return f"resource://agents/{agent_id}/ui/state"
    ```

    **What's actually mounted (server.py, lines 251-284):**
    ```python
    @self.resource("resource://agents/list", name="agents_list", ...)
    async def list_agents() -> AgentsListResponse:
        ...

    @self.resource("resource://agents/{agent_id}/info", name="agent_info", ...)
    async def get_agent_info(agent_id: AgentID) -> AgentInfo:
        ...
    ```

    **Problems:**

    1. **Dead code**: 10 URI helper functions defined but never used
    2. **Confusing API**: Functions suggest resources exist when they don't
    3. **Maintenance burden**: Must maintain unused code and its documentation
    4. **Misleading documentation**: Docstrings describe non-existent resources
    5. **No clear plan**: Unclear if these are intended future features or abandoned work
    6. **Constants duplication**: Same URIs also defined in `_shared/constants.py`

    **The correct approach:**

    Either implement the resources or delete the unused helpers:

    **Option 1: Delete unused helpers (recommended if not needed)**
    ```python
    # resources.py
    from adgn.agent.types import AgentID

    # Only keep what's actually mounted
    AGENTS_LIST = "resource://agents/list"

    def agent_info(agent_id: AgentID) -> str:
        """Resource URI for agent information."""
        return f"resource://agents/{agent_id}/info"
    ```

    **Option 2: Implement the missing resources (if they're needed)**
    ```python
    # server.py
    @self.resource("resource://agents/{agent_id}/state", ...)
    async def get_agent_state(agent_id: AgentID) -> AgentStateResponse:
        agent = self._get_agent_or_raise(agent_id)
        return AgentStateResponse(
            agent_id=agent_id,
            sampling_state=agent.running.sampling_state if agent.running else None,
            ...
        )

    @self.resource("resource://agents/{agent_id}/snapshot", ...)
    async def get_agent_snapshot(agent_id: AgentID) -> SnapshotResponse:
        ...
    ```

    **Benefits of cleanup:**

    1. **No dead code**: Only code that's actually used
    2. **Clear API surface**: Functions match actual capabilities
    3. **Less confusion**: New developers don't waste time investigating non-existent resources
    4. **Smaller maintenance burden**: Fewer docstrings and functions to maintain
    5. **Honest documentation**: Code accurately reflects what's implemented

    **Migration strategy:**

    1. Search for all usages of these functions across the codebase
    2. If any are used (e.g., in tests that expect future implementation), replace with inline strings or move to a "planned" module
    3. Delete unused functions from resources.py
    4. Update any documentation that references the removed URIs
    5. If functions ARE used somewhere, investigate why resources aren't mounted

    **Related issues:**

    This is related to the constants duplication in `_shared/constants.py` - those constants
    define the same URIs and should be the single source of truth if these resources are
    eventually implemented.
  |||,
  properties=['remove-dead-code', 'avoid-speculative-code'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/resources.py': [
      [16, 67],  // All unmounted URI helper functions (agent_state through agent_ui_state)
    ],
  },
  gap_note= |||
    This finding illustrates **"avoid-speculative-code"**: don't write infrastructure
    for features that aren't implemented yet. Either implement the feature completely or
    don't add the infrastructure.

    Speculative code causes:
    - Dead code that never gets used (increases maintenance burden)
    - Misleading APIs (functions suggest capabilities that don't exist)
    - Confusion (is this a bug, or intentionally unimplemented?)
    - Broken windows (more speculative code gets added because it exists)

    The principle: write code when you need it, not when you might need it.

    Exceptions (when speculative code is acceptable):
    - Explicit feature flags or capability detection (so code knows what's available)
    - Well-documented TODOs or NotImplementedError stubs (make intent clear)
    - Interface definitions in a stable API contract (but mark unimplemented methods)

    Related to **"remove-dead-code"**: once you identify that code is unused, delete it.
    Don't keep it around "just in case" - version control preserves history if needed later.

    When you find helper functions that construct identifiers/URIs for things that
    don't exist:
    1. Check if they're used anywhere (search imports)
    2. If used only in tests expecting future work: move to test fixtures
    3. If unused: delete immediately
    4. If implementing: add the actual functionality at the same time
  |||,
)
