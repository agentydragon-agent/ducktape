local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    _pending_notifier accepts three primitive parameters and reconstructs ToolCall
    (infrastructure.py:197-200):

    async def _pending_notifier(call_id: str, tool_key: str, args_json: str | None) -> None:
        ...
        tool_call = ToolCall(name=tool_key, call_id=call_id, args_json=args_json)
        await self._connection_manager.send_payload(...)

    The notifier immediately reconstructs the ToolCall object from its parts.
    The caller must have had a ToolCall to decompose into these parameters.

    Should accept ToolCall directly:
    async def _pending_notifier(tool_call: ToolCall) -> None:
        ...
        await self._connection_manager.send_payload(
            ApprovalPendingEvt(approval=ApprovalBrief(tool_call=tool_call))
        )

    Benefits:
    - Simpler interface: one parameter instead of three
    - Type safety: caller can't mix up parameter order
    - No decompose-then-reconstruct
    - Clearer contract: "notify about this tool call"

    The current signature suggests legacy from when ToolCall didn't exist as a type.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/runtime/infrastructure.py': [
      [197, 203],   // _pending_notifier definition and ToolCall reconstruction
    ],
  }
)
