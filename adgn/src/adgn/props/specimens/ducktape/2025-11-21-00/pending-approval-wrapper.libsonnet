local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 120-124 define `PendingApproval` wrapper with fields `tool_call: ToolCall` and `timestamp: datetime`.
    Lines 50-59 define `_convert_pending_approvals()` that loops over `pending_map.items()`, wraps each
    `ToolCall` in `PendingApproval` with `timestamp=datetime.now()`. Used at 3 call sites (lines 386, 404, 444).

    This is unnecessary indirection with misleading timestamp: line 56 sets `datetime.now()` at query time,
    not creation time (TODO comment acknowledges this is wrong). After removing timestamp, wrapper and
    conversion become trivial. Creates intermediate objects when callers could use dict values directly.

    Delete `PendingApproval` class (lines 120-124) and `_convert_pending_approvals()` function (lines 50-59).
    Replace call sites with `list(pending_map.values())`. Update return types from `list[PendingApproval]`
    to `list[ToolCall]`. Eliminates misleading timestamp, unnecessary wrapper, and conversion overhead.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [120, 124],  // PendingApproval wrapper class
      [50, 59],    // _convert_pending_approvals function
      [56, 56],    // Misleading timestamp=datetime.now() with TODO
      [386, 386],  // Call site 1
      [404, 404],  // Call site 2
      [444, 444],  // Call site 3
    ],
  },
)
