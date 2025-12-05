local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 150-158 create a ToolCallRecord with 6 fields (call_id, run_id, agent_id, tool_call,
    decision=None, execution=None) and assign it to `pending_record`, which is used exactly once
    on line 158 for `save_tool_call()`.

    Single-use variables add cognitive overhead without providing value. Inline the construction
    directly into the save call to eliminate the unnecessary intermediate variable.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [150, 158],  // pending_record creation and single use
    ],
  },
)
