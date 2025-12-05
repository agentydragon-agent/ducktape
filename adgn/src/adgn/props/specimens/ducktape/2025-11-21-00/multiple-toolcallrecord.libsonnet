local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `on_call_tool` method constructs 8 independent ToolCallRecord instances at lines 150-158,
    180-188, 195-205, 263-271, 278-286, 302-310, 317-327, and 339-347, each repeating the same
    4-7 field assignments (call_id, run_id, agent_id, tool_call, decision, execution).

    This massive code duplication (~100 lines of redundancy) violates DRY. Field assignments
    obscure the actual state transitions (PENDING → EXECUTING → COMPLETED, or DENIED paths).
    When fields change, all 8 constructions must be updated, making maintenance error-prone.

    Create ONE mutable ToolCallRecord instance at the start. At each state transition, update only
    the changed fields (set .decision or .execution), then save. This eliminates redundancy, makes
    state transitions explicit, and ensures single source of truth for record fields.

    Requires ToolCallRecord to be mutable (dataclass with frozen=False, or Pydantic with frozen=False).
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/middleware.py': [
      [142, 358],  // Entire on_call_tool method
      [150, 158],  // Construction 1: pending_record
      [180, 188],  // Construction 2: ALLOW executing_record
      [195, 205],  // Construction 3: ALLOW completed_record
      [263, 271],  // Construction 4: DENY_ABORT denied_record
      [278, 286],  // Construction 5: DENY_CONTINUE denied_record
      [302, 310],  // Construction 6: ASK/approved executing_record
      [317, 327],  // Construction 7: ASK/approved completed_record
      [339, 347],  // Construction 8: ASK/denied denied_record
    ],
  },
)
