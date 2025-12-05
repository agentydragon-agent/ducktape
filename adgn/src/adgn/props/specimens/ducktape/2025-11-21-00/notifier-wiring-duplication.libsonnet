local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Four notifier factory functions (lines 841-855, 858-878, 884-898, 901-915) follow the
    exact same pattern with duplicated boilerplate: sync notifier schedules broadcast in
    event loop via `loop.create_task(server.broadcast_resource_updated(uri))` with
    `add_done_callback` for success/failure logging, fire-and-forget.

    **Duplicated notifiers:**
    1. `make_policy_notifier` (841-855) - takes URI parameter
    2. `make_approval_hub_notifier` (858-878) - broadcasts 3 approval resources
    3. `make_ui_state_notifier` (884-898) - uses `resources.agent_ui_state(aid)`
    4. `make_session_state_notifier` (901-915) - uses `resources.agent_session_state(aid)`

    **Why this is problematic:**
    - Same 10-15 line pattern repeated 4 times (~60 lines total)
    - Changes to broadcast pattern must update 4 identical copies
    - Error-prone: easy to update one notifier but forget others

    **Fix:** Extract into `make_sync_broadcast_notifier(uri_getter, log_context)` helper that
    handles the common pattern (get URIs, schedule broadcasts, add callbacks). Reduces to ~15
    lines + 4 simple calls. Note: `make_mount_listener` (lines 918-926) is different (async,
    awaits broadcast) and should not be included.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [841, 855],
      [858, 878],
      [884, 898],
      [901, 915],
    ],
  },
)
