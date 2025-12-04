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
    The policy gateway tracks in-flight tool calls via direct Python field access
    (_policy_gateway.has_inflight_calls()) instead of exposing state through MCP
    resources and notifications. This breaks the architectural pattern where all
    state is accessed through MCP.

    **Architectural inconsistency:**
    - compositor_meta exposes mount state as MCP resources (lines 35-47)
    - AgentSession (runtime.py:90-95) and status builder (status_shared.py:60-65)
      directly access _policy_gateway.has_inflight_calls()
    - Frontend listens to MCP notifications but can't see "executing" state

    **Problems:**
    1. Inconsistent: everything else uses MCP resources, this uses direct access
    2. Tight coupling: direct field access creates module dependencies
    3. Missing states: tool calls show only WAITING_APPROVAL vs completed, no
       intermediate "executing" state
    4. Frontend can't show "executing" status

    **Fix:** Expose tool call states (pending_approval, executing, completed) as
    MCP resources. Policy gateway emits resource_updated notifications when state
    changes. AgentSession/status read state via MCP resources instead of direct access.

    **Benefits:** Architectural consistency, better UI (shows executing state),
    decoupling, tool call lifecycle fully visible through notifications.
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
