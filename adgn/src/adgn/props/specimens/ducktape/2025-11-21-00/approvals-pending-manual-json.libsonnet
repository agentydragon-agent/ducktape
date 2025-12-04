local I = import '../lib.libsonnet';

// iss-029: approvals_pending_global hand-constructs JSON instead of using Pydantic

I.issue(
  snapshot='ducktape/2025-11-21-00',
  rationale=|||
    The `approvals_pending_global` function (lines 395-424) manually constructs JSON dicts
    using `json.dumps()` instead of Pydantic models, losing type safety and validation.

    **Problems:**

    1. Manual dict construction with string keys - typos aren't caught (`{"call_idd": x}`)
    2. No validation - wrong types slip through (`{"call_id": 123}` should be str)
    3. Manual `json.dumps()` instead of Pydantic serialization
    4. Hard to evolve - field changes require manual updates
    5. Inconsistent with codebase - other functions use Pydantic (AgentApprovalsPending, etc.)
    6. Nested tool_call dict manually constructed when ToolCall model exists
    7. No IDE autocomplete or type checking

    **Fix:**

    Define Pydantic models and use them:

    ```python
    class PendingApprovalItem(BaseModel):
        call_id: str
        tool_call: ToolCall

    class AgentPendingApprovalsBlock(BaseModel):
        agent_id: AgentID
        pending: list[PendingApprovalItem]

    class ResourceBlock(BaseModel):
        uri: str
        mimeType: str
        text: str

    async def approvals_pending_global() -> list[ResourceBlock]:
        result: list[ResourceBlock] = []
        for agent_id in registry.known_agents():
            # ... check infra ...
            pending_items = [
                PendingApprovalItem(call_id=call_id, tool_call=tc)
                for call_id, tc in pending.items()
            ]
            agent_block = AgentPendingApprovalsBlock(agent_id=agent_id, pending=pending_items)
            result.append(ResourceBlock(
                uri=f"resource://agents/{agent_id}/approvals/pending",
                mimeType="application/json",
                text=agent_block.model_dump_json()
            ))
        return result
    ```

    **Benefits:** Type safety, automatic validation, IDE support, consistent with codebase,
    uses existing ToolCall model, framework handles serialization.

    **Related:** Issue 026 (list_agents manual JSON) - both should be refactored together.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [395, 424],  // approvals_pending_global with manual dict construction
      [411, 419],  // Manual pending_list dict construction
      [421, 424],  // Manual result dict construction with json.dumps
    ],
  },
)
