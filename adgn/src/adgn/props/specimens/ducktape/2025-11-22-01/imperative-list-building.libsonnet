local I = import '../../lib.libsonnet';

// Merged: imperative-list-building, imperative-approvals-list, imperative-proposals-list
// All describe imperative append() loops that should use list comprehensions

I.issue(
  expect_caught_from=[['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'], ['adgn/src/adgn/agent/mcp_bridge/servers/approvals_bridge.py'], ['adgn/src/adgn/agent/server/runtime.py']],
  rationale= |||
    Three functions build lists imperatively using `append()` in loops instead of list comprehensions.

    Lines 50-59 in agents.py define `_convert_pending_approvals()` that initializes empty list,
    loops over `pending_map.items()`, and appends `PendingApproval` objects. The function doesn't
    use `call_id`, so should iterate `.values()` directly.

    Lines 64-108 in approvals_bridge.py build `approvals_list` with two separate loops: lines 71-80
    append pending approvals, lines 99-108 append decided approvals (with conditional). Both should
    use comprehensions and combine via `pending_approvals + decided_approvals`.

    Lines 267-274 in runtime.py build `proposals` list with nested conditional and loop: checks
    persistence/agent_id, iterates rows, creates intermediate `pid`/`raw` vars, appends. Should use
    conditional expression with comprehension.

    Replace imperative `result = []; for x in items: result.append(transform(x))` pattern with
    comprehensions: `[transform(x) for x in items]`. This is more concise, Pythonic, immutable
    (no list mutation), and clearer intent.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [50, 59],   // _convert_pending_approvals: loop-and-append
      [52, 52],   // Iterates .items() but doesn't use call_id (should use .values())
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/approvals_bridge.py': [
      [64, 65],   // approvals_list initialization
      [71, 80],   // pending approvals loop
      [99, 108],  // decided approvals loop
    ],
    'adgn/src/adgn/agent/server/runtime.py': [
      [267, 274], // proposals list building with for loop
    ],
  },
)
