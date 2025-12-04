local I = import '../../lib.libsonnet';


I.issue(
  // Detection requires seeing BOTH the tracking mechanism AND either a consumer or the pattern.
  // From middleware.py alone, can't tell this state is meant for external exposition.
  // Need to see either:
  //   - Direct access (runtime.py/status_shared.py) showing the violation, OR
  //   - Pattern exemplar (compositor_meta) showing the correct approach
  expect_caught_from=[
    ['adgn/src/adgn/mcp/policy_gateway/middleware.py', 'adgn/src/adgn/agent/server/runtime.py'],         // Tracking + consumer
    ['adgn/src/adgn/mcp/policy_gateway/middleware.py', 'adgn/src/adgn/agent/server/status_shared.py'],  // Tracking + consumer
    ['adgn/src/adgn/mcp/policy_gateway/middleware.py', 'adgn/src/adgn/mcp/compositor_meta/server.py'],  // Tracking + pattern
  ],
  rationale= |||
    The policy gateway tracks in-flight tool calls via direct field access
    (`_policy_gateway.has_inflight_calls()`), but this breaks the architectural pattern
    where all state is accessed through MCP resources and notifications.

    **Correct pattern (see compositor_meta/server.py):**
    The `compositor_meta` server exposes mount state as MCP resources at
    `resource://compositor_meta/state/{server}` and emits `resource_updated` notifications
    when state changes. This is how the system exposes execution progress to the frontend.

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
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [128, 128],  // _inflight: dict[str, str] tracking (should be MCP resource)
      [130, 136],  // has_inflight_calls(), inflight_count() (direct Python API, should be MCP)
      [145, 180],  // on_call_tool where _inflight is updated (should emit notifications)
    ],
    'adgn/src/adgn/agent/server/runtime.py': [
      [90, 95],  // current_run_phase() using _policy_gateway.has_inflight_calls() (direct access violation)
    ],
    'adgn/src/adgn/agent/server/status_shared.py': [
      [60, 65],  // build_agent_status_core using c._policy_gateway.has_inflight_calls() (direct access violation)
    ],
    'adgn/src/adgn/agent/runtime/container.py': [
      [197, 197],  // _policy_gateway field stored for direct access
      [372, 372],  // policy_gateway= parameter enabling direct access
    ],
    'adgn/src/adgn/mcp/compositor_meta/server.py': [
      [35, 47],  // Pattern exemplar: expose state as MCP resources with notifications
    ],
  },
)
