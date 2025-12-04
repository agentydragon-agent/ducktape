local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 395-424 define `approvals_pending_global` that manually constructs JSON dicts with
    string keys and `json.dumps()` instead of using Pydantic models.

    Problems: manual dict construction doesn't catch typos (`{"call_idd": x}`); no validation
    (wrong types like `{"call_id": 123}` slip through); hard to evolve (field changes require
    manual updates across dict literals); inconsistent with codebase (other functions use
    Pydantic like AgentApprovalsPending); nested tool_call dict manually constructed despite
    existing ToolCall model; no IDE autocomplete or type checking.

    Lines 411-419 manually build pending_list dicts; lines 421-424 manually construct result
    dicts with json.dumps.

    Replace with Pydantic models (PendingApprovalItem, AgentPendingApprovalsBlock, ResourceBlock)
    and use model_dump_json() for serialization. Benefits: type safety, automatic validation,
    IDE support, reuses existing ToolCall model, framework handles serialization.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [395, 424],  // approvals_pending_global with manual dict construction
      [411, 419],  // Manual pending_list dict construction
      [421, 424],  // Manual result dict construction with json.dumps
    ],
  },
)
