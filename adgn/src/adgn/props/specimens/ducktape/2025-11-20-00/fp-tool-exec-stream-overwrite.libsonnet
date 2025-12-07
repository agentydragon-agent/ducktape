local I = import '../../lib.libsonnet';

I.falsePositive(
  rationale= |||
    Critics flagged update_tool_exec_stream (lines 142-171) for overwriting stdout/stderr instead
    of appending, claiming that multiple FunctionCallOutput events could be emitted for the same
    call_id with progressive chunks. However, the actual execution flow shows this doesn't happen:

    1. on_tool_result_event (runtime.py:209-214) receives ONE ToolCallOutput per tool call
       completion (ToolCallOutput is documented as containing the complete result)
    2. Creates ONE FunctionCallOutput from it: `fco = FunctionCallOutput(call_id=evt.call_id,
       result=convert_fastmcp_result(evt.result))`
    3. Sends to reducer once via `_send_and_reduce(fco)`
    4. Reducer (reducer.py:101-150) calls update_tool_exec_stream once with the complete result

    There is no streaming/chunking mechanism - tools return complete results in a single event.
    The overwrite logic is correct for the current single-event model.

    However, the code is misleading: the function name "update_tool_exec_stream" and the reducer
    comment "merge stdout/stderr/exit" (line 101) both suggest that multiple progressive outputs
    might arrive, which made critics reasonably flag this as a potential bug. This misleading
    naming/commenting is captured as a separate true positive issue (tool-exec-stream-misleading-naming.libsonnet).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [[142, 171]],
    'adgn/src/adgn/agent/server/runtime.py': [[209, 214]],
    'adgn/src/adgn/agent/server/reducer.py': [[101, 150]],
  },
  relevant_files=[
    'adgn/src/adgn/agent/server/state.py',
    'adgn/src/adgn/agent/server/runtime.py',
    'adgn/src/adgn/agent/server/reducer.py',
  ],
)
