local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 255-258 build `calls: list[tuple[FunctionCallItem, str | None]]` duplicating
    `function_call.arguments` when it's already in the `FunctionCallItem` object.

    Current: constructs tuples `(function_call, function_call.arguments)`, then passes
    both `calls` (tuples) and `function_calls` (original list) to
    `_run_tool_calls_parallel` and `_run_tool_calls_sequential` (lines 291, 293).

    Sequential usage (line 336): `for i, (function_call, args_json) in enumerate(calls):`
    then `invoker(function_call, args_json)`. Could iterate `function_calls` directly
    and access `function_call.arguments`.

    Parallel usage (line 305): `runner(fc: FunctionCallItem, aj: str | None)` then
    unpacks tuples at line 310. Could take only `FunctionCallItem` and access
    `fc.arguments` inside.

    **Fix:** Delete tuple construction, pass only `function_calls` to both methods,
    access `.arguments` directly, remove tuple unpacking. Benefits: no duplication,
    simpler code, one less list, clearer that we're working with objects.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/agent.py': [
      [255, 258],  // Redundant tuple construction
      [291, 291],  // Call to _run_tool_calls_parallel with both lists
      [293, 293],  // Call to _run_tool_calls_sequential with both lists
      [296, 298],  // _run_tool_calls_parallel signature
      [333, 335],  // _run_tool_calls_sequential signature
      [336, 336],  // Sequential unpacking of tuple
      [305, 305],  // Parallel runner signature
      [310, 310],  // Parallel iteration over calls
    ],
  },
)
