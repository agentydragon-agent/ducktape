local I = import '../../specimens/lib.libsonnet';

// Merged: imperative-list-building, imperative-approvals-list, imperative-proposals-list
// All describe imperative append() loops that should use list comprehensions

I.issueOneOccurrence(
  rationale= |||
    Multiple functions build lists imperatively using `append()` in loops when
    list comprehensions would be more concise, readable, and Pythonic.

    **Pattern: Initialize empty list, loop, append**

    This non-idiomatic pattern appears in three locations:

    **Location 1: _convert_pending_approvals (agents.py:50-59)**
    ```python
    def _convert_pending_approvals(pending_map: dict[str, ToolCall]) -> list[PendingApproval]:
        result: list[PendingApproval] = []
        for _call_id, tool_call in pending_map.items():
            result.append(PendingApproval(...))
        return result
    ```

    **Location 2: list_approvals (approvals_bridge.py:64-108)**
    ```python
    approvals_list = []
    pending_count = 0

    # Add pending approvals
    for call_id, tool_call in pending_map.items():
        approvals_list.append(ApprovalItem(...))
        pending_count += 1

    # Add decided approvals
    for record in records:
        if record.decision is not None:
            approvals_list.append(ApprovalItem(...))
            decided_count += 1
    ```

    **Location 3: get_policy (runtime.py:267-274)**
    ```python
    proposals: list[ProposalInfo] = []
    if self._persistence is not None and self.agent_id:
        rows = await self._persistence.list_policy_proposals(self.agent_id)
        for r in rows:
            pid = str(r.id)
            raw = str(r.status)
            proposals.append(ProposalInfo(id=pid, status=ProposalStatus(raw)))
    ```

    **Problems with imperative style:**
    - Verbose (extra lines for initialization and loop mechanics)
    - Mutable state (list mutated via append)
    - Less Pythonic (comprehensions preferred for transformations)
    - Intent unclear (must parse loop to see it's a map operation)
    - Unnecessary intermediate variables in some cases

    **Correct approach: Use list comprehensions**

    Location 1:
    ```python
    def _convert_pending_approvals(pending_map: dict[str, ToolCall]) -> list[PendingApproval]:
        return [
            PendingApproval(
                tool_call=tool_call,
                timestamp=datetime.now(),
            )
            for tool_call in pending_map.values()  # Use .values() since call_id unused
        ]
    ```

    Location 2:
    ```python
    # Pending approvals
    pending_approvals = [
        ApprovalItem(
            call_id=call_id,
            tool_call=tool_call,
            status=ApprovalStatus.PENDING,
            reason=None,
            timestamp=datetime.now(),
        )
        for call_id, tool_call in self._hub.pending.items()
    ]

    # Decided approvals
    decided_approvals = [
        ApprovalItem(
            call_id=record.tool_call.id,
            tool_call=record.tool_call,
            status=_map_outcome_to_status(record.decision.outcome),
            reason=record.decision.reason,
            timestamp=record.decision.decided_at,
        )
        for record in await self._persistence.get_tool_call_records(self._agent_id)
        if record.decision is not None
    ]

    approvals_list = sorted(
        pending_approvals + decided_approvals,
        key=lambda x: x.timestamp,
        reverse=True
    )
    ```

    Location 3:
    ```python
    proposals = (
        [
            ProposalInfo(id=str(r.id), status=ProposalStatus(str(r.status)))
            for r in await self._persistence.list_policy_proposals(self.agent_id)
        ]
        if self._persistence is not None and self.agent_id
        else []
    )
    ```

    **Benefits:**
    - More concise and readable
    - Immutable (no list mutation)
    - Pythonic (idiomatic for simple transformations)
    - Clearer intent (obviously building list from iterable)
    - Eliminates unnecessary intermediate variables
    - Type inference more obvious
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
