local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 104-107 define `start_tool()` which takes individual `tool`, `call_id` parameters
    then fabricates a `ToolCall` object internally. This unbundles existing structure from
    callers and loses information.

    **Problems:**
    1. Callers likely already have a `ToolCall` object but must unbundle it
    2. Hardcodes `args_json=None`, losing actual value
    3. Requires 4 keyword params instead of 2
    4. Function must know ToolCall internals to reconstruct it

    **Fix:** Accept `tool_call: ToolCall` directly instead of `tool` and `call_id` separately.
    This preserves all fields (including args_json), reduces parameters, and respects existing
    bundling. Callers pass the ToolCall as-is without unbundling.

    Alternatively, if cmd/args should also be bundled, accept both `tool_call: ToolCall` and
    `content: ToolContent` for a two-parameter signature.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [
      [104, 107],  // start_tool with unbundled parameters
    ],
  },
)
