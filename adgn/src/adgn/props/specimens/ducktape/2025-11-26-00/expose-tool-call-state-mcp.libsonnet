local I = import '../../lib.libsonnet';

// iss-002: Policy gateway tool call state should be exposed via MCP resources

I.issue(
  snapshot='ducktape/2025-11-26-00',
  expect_caught_from=[
    ['adgn/src/adgn/agent/runtime/container.py'],
    ['adgn/src/adgn/agent/server/runtime.py'],
    ['adgn/src/adgn/agent/server/status_shared.py'],
    ['adgn/src/adgn/mcp/policy_gateway/middleware.py'],
  ],
  rationale= |||
    The policy gateway tracks in-flight tool calls via direct field access
    (`_policy_gateway.has_inflight_calls()`), but this breaks the architectural pattern
    where all state is accessed through MCP resources and notifications.

    **Current architecture:**
    - AgentSession directly accesses `self._policy_gateway.has_inflight_calls()` (runtime.py)
    - Status builder directly accesses `c._policy_gateway.has_inflight_calls()` (status_shared.py)
    - Frontend listens to tool call state changes via MCP resource notifications

    **Problems:**
    1. **Inconsistent architecture**: Everything else uses MCP resources, this uses direct access
    2. **Limited frontend integration**: Frontend already listens to tool call state changes,
       but can't see "being executed" state because it's not exposed as MCP resources
    3. **Tight coupling**: Direct field access creates dependencies between modules
    4. **Missing states**: Tool calls only show WAITING_APPROVAL vs completed, missing
       intermediate states like "executing" or "handed off to compositor"

    **Correct approach:**
    - Policy gateway should update tool call resources with more states:
      - "pending_approval" (already exists, in ApprovalHub.pending)
      - "executing" (currently in policy_gateway._inflight, between approval and completion)
      - "completed" (already exists)
    - Expose tool call states via MCP resources (similar to existing approval resources)
    - Emit resource change notifications when tool call state changes
    - Frontend listens to these notifications (already has infrastructure for this)
    - AgentSession and status builder read state via MCP resources instead of direct access

    **Benefits:**
    1. **Architectural consistency**: All state accessed through MCP, not direct references
    2. **Better UI**: Frontend can show "Tool executing..." instead of just "Waiting..."
    3. **Decoupling**: No direct dependencies between policy gateway and session/status
    4. **Extensibility**: Adding new states just means emitting more notifications
    5. **Unified system**: Tool call lifecycle is fully visible through resource notifications

    **Implementation notes:**
    - Tool call states flow: approval_pending → executing → completed
    - Policy gateway already emits notifications for approval state
    - Just needs to emit notifications for executing state (in _inflight tracking)
    - AgentSession.current_run_phase() should check MCP resources instead of direct access
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/container.py': [
      [197, 197],  // _policy_gateway field (direct access point)
      [372, 372],  // policy_gateway= parameter passed to AgentSession
    ],
    'adgn/src/adgn/agent/server/runtime.py': [
      [90, 95],  // current_run_phase() using _policy_gateway.has_inflight_calls()
    ],
    'adgn/src/adgn/agent/server/status_shared.py': [
      [60, 65],  // build_agent_status_core using c._policy_gateway.has_inflight_calls()
    ],
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [70, 80],  // _inflight tracking dict (should emit MCP notifications)
      [120, 135],  // on_call_tool where _inflight is updated
    ],
  },
)
