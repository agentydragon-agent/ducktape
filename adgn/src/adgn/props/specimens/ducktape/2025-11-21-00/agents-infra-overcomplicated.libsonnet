local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
    ['adgn/src/adgn/agent/mcp_bridge/server.py'],
    ['adgn/src/adgn/agent/approvals.py'],
  ],
  rationale=|||
    The agents MCP bridge uses a complex two-layer observer pattern (business logic → callbacks
    → AgentsServer → MCP clients) instead of the simpler compositor pattern already used
    successfully on the agent side.

    **Current Architecture Problems:**

    1. **Two-layer complexity:** Business logic calls sync callbacks that schedule async tasks
       that eventually broadcast. Lines 833-932 contain ~100 lines of factory functions.

    2. **Clobbered notifier bug (Issue 037):** ApprovalPolicyEngine has only ONE notifier slot.
       When agents.py:855 wires its notifier, it replaces the one from ApprovalPolicyServer,
       breaking notifications.

    3. **Monolithic server:** AgentsServer aggregates resources from 6+ business logic classes.
       Hard to test independently.

    4. **URI scoping inconsistency (Issue 038):** Global URIs (`resource://approval-policy/*`)
       mixed with agent-scoped URIs (`resource://agents/{id}/*`).

    **Better: Compositor Pattern**

    Replace monolithic AgentsServer with small focused servers mounted in a compositor, like
    the agent-side does (agent/runtime/infrastructure.py:100-114). Each server wraps one
    business logic class and directly broadcasts MCP notifications.

    Example structure:
    - ApprovalPolicyServer wraps ApprovalPolicyEngine
    - ApprovalsServer wraps ApprovalHub
    - SessionStateServer wraps Session
    - AgentRegistryServer wraps AgentRegistry

    Mount all in compositor with proper namespacing (`agent_{id}_policy`, etc.). Notifications
    propagate automatically via compositor's _ChildHandler (compositor/server.py:446-469).

    **Benefits:**

    - Eliminates callback layer - servers directly broadcast to MCP clients
    - Fixes clobbered notifier bug - each server manages its own subscriptions
    - Natural namespacing via server prefixes
    - Eliminates 100 lines of manual wiring code (lines 833-932)
    - Independently testable without mocking callbacks
    - Reuses proven pattern from agent-side
    - Dynamic mounting via compositor API

    **Refactoring needed:**

    - agents.py (833 lines) → Replace with small server files
    - server.py → Use compositor instead of single FastAPI app
    - Business logic classes → Remove notifier fields, add `*_without_notify()` methods
    - Lines 833-932 → Delete wiring code, mount servers in compositor

    **Related:** Issues 036 (notification wiring duplication), 037 (notifier pattern bugs),
    038 (URI scoping). All solved by compositor pattern.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [1, 932],  // Entire monolithic AgentsServer file
      [833, 932],  // Notification wiring code (Issue 036)
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [1, 258],  // InfrastructureRegistry and HTTP bridge setup
    ],
    'adgn/src/adgn/agent/approvals.py': [
      [96, 110],   // ApprovalHub with _notifier field
      [146, 195],  // ApprovalPolicyEngine with _notify field
    ],
  },
)
