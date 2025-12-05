local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `pending_count` field in `ApprovalsResponse` is redundant because it's derived
    information that can be computed from the already-returned `approvals` list by counting
    items with `status == ApprovalStatus.PENDING`.

    Current implementation manually counts pending approvals while building the list:
    ```python
    pending_count = 0
    # ...
    for call_id, tool_call in pending_map.items():
        approvals_list.append(...)
        pending_count += 1
    ```

    This violates DRY (Don't Repeat Yourself) - the client already has all the information
    needed to compute pending_count from the approvals list.

    Fix: Remove the `pending_count` and `decided_count` fields from `ApprovalsResponse`.
    Clients can compute these values trivially:
    ```python
    pending_count = len([a for a in approvals if a.status == ApprovalStatus.PENDING])
    decided_count = len([a for a in approvals if a.status != ApprovalStatus.PENDING])
    ```

    This simplifies the server code and reduces the chance of count/list mismatch bugs.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/approvals_bridge.py': [
      38,  // pending_count field
      65,  // pending_count increment
      80,  // decided_count increment
      116, // pending_count in response
    ],
  },
)
