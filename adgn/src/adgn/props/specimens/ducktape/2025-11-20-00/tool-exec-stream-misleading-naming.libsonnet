local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The function name update_tool_exec_stream (state.py:142) and the reducer comment "merge
    stdout/stderr/exit" (reducer.py:101) both suggest that multiple FunctionCallOutput events
    may arrive progressively for a single tool call, requiring merging/appending of output streams.
    However, the actual execution flow guarantees exactly one FunctionCallOutput per call_id: tools
    return complete results in a single event (on_tool_result_event in runtime.py:209-214 receives
    one ToolCallOutput and creates one FunctionCallOutput from it). The naming and comment are
    misleading - they suggest a streaming/progressive update model that doesn't exist in the
    current architecture. The function should be named something like set_tool_exec_result or
    update_tool_output to reflect that it sets the complete output once, and the "merge" comment
    should clarify that it's extracting fields from a single complete result, not merging across
    multiple events.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [[142, 142]],
    'adgn/src/adgn/agent/server/reducer.py': [[101, 101]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/state.py'],
    ['adgn/src/adgn/agent/server/reducer.py'],
  ],
)
