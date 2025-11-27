# Policy Server Consolidation Plan

## Goal

Consolidate policy and approval handling into a clean 3-server architecture with proper separation between agent-facing and user-facing compositors.

## Current State

### Servers (mounted names)
| Name | Type | Purpose |
|------|------|---------|
| `approval_policy` | NotifyingFastMCP | Policy evaluation, resources |
| `approval_policy.proposer` | FastMCP | Policy change proposals |
| `approval_policy.approver` | FastMCP | Policy admin (NOT mounted, private client) |
| `approvals` | NotifyingFastMCP | Tool call approval actions |

### Problems
1. **Redundant servers**: `approvals` is separate from policy servers despite being part of the same flow
2. **Private client hack**: `approval_policy.approver` not mounted, accessed via weird private client
3. **Fragmented tools**: `approve_call`, `deny_abort`, `deny_continue` as separate tools
4. **Unclear naming**: `approval_policy` vs `approvals` is confusing
5. **Notification plumbing**: Complex callback wiring between hub and servers

## Target Architecture

### Two Compositors
1. **Agent compositor**: What the agent's MCP client connects to (policy-gated)
2. **User compositor**: What the user/UI connects to (admin capabilities)

### Three Servers

| Mount Name | Type | Mounted On | Purpose |
|------------|------|------------|---------|
| `policy.reader` | NotifyingFastMCP | agent + user | Read policy, evaluate, view pending |
| `policy.proposer` | FastMCP | agent | Propose policy changes |
| `approver` | FastMCP | user only | Approve/deny calls and proposals |

### ApprovalHub

`ApprovalHub` (in `adgn/agent/approvals.py`) is an in-process rendezvous for tool call approval flow:

```python
class ApprovalHub:
    """Coordinates pending tool call approvals between middleware and UI."""

    async def await_decision(call_id, request) -> ContinueDecision | AbortTurnDecision
        # Called by PolicyGatewayMiddleware when policy returns ASK
        # Blocks until resolve() is called

    def resolve(call_id, decision)
        # Called by approver server when user decides
        # Unblocks the waiting await_decision()

    @property
    def pending -> dict[str, ApprovalRequest]
        # Current pending requests (for resource)

    def set_on_change(callback)
        # Register notification callback (for resource updates)
```

**Ownership**: `PolicyEngine` owns the hub. Reader registers for change notifications to broadcast resource updates.

### Resource URIs

| URI | Server | Description |
|-----|--------|-------------|
| `policy://source` | reader | Current policy source code |
| `policy://proposals` | reader | Policy change proposals index |
| `policy://proposals/{id}` | reader | Individual proposal |
| `pending://calls` | reader | Pending tool call approvals |

Note: `pending://` not `policy://` for pending calls - they're runtime state, not policy definitions.

### Tools

#### policy.reader
- `evaluate_policy(name, arguments)` - Evaluate policy for a tool call

#### policy.proposer
- `propose_policy_change(content)` - Create a policy change proposal
- `withdraw_proposal(id)` - Withdraw own proposal

#### approver
- `decide_call(call_id, decision: CallDecision)` - Approve/deny a pending tool call
  ```python
  class CallDecision(str, Enum):
      APPROVE = "approve"      # Allow the call
      DENY_ABORT = "deny_abort"    # Deny and abort turn
      DENY_CONTINUE = "deny_continue"  # Deny but continue turn
  ```

- `decide_proposal(proposal_id, decision: ProposalDecision)` - Approve/reject a policy proposal
  ```python
  class ProposalDecision(str, Enum):
      APPROVE = "approve"
      REJECT = "reject"
  ```

- `set_policy(source)` - Directly set policy (admin override)

## Implementation Steps

### Phase 1: Consolidate into PolicyEngine

1. **Move pending calls resource to reader**
   - Add `pending://calls` resource to reader server
   - Wire hub's `set_on_change` to reader's broadcast
   - Resource returns `hub.pending` formatted as JSON

2. **Add decide_call tool to approver**
   - Create `CallDecision` enum
   - Single `decide_call(call_id, decision)` tool
   - Calls `hub.resolve()` with appropriate decision type

3. **Consolidate decide_proposal tool**
   - Create `ProposalDecision` enum
   - Replace `approve_proposal`/`reject_proposal` with `decide_proposal(id, decision)`

4. **PolicyEngine owns hub**
   - Move `ApprovalHub` creation into `PolicyEngine.__init__`
   - Expose via `engine.hub` property
   - Wire reader's broadcast callback internally

### Phase 2: Delete approvals module

1. Delete `adgn/mcp/approvals/` directory entirely
2. Remove `attach_approvals` call from container.py
3. Remove `APPROVALS_SERVER_NAME` constant

### Phase 3: Update container.py

1. Remove private client hack for approver
2. Mount approver on user compositor (when user compositor exists)
3. For now: mount approver alongside reader/proposer (temporary)
4. Remove `_policy_approver` field and related setup

### Phase 4: Rename constants

```python
# Old
APPROVAL_POLICY_SERVER_NAME = "approval_policy"
APPROVAL_POLICY_SERVER_NAME_READER = "approval_policy"
APPROVAL_POLICY_SERVER_NAME_PROPOSER = "approval_policy.proposer"
APPROVAL_POLICY_SERVER_NAME_APPROVER = "approval_policy.approver"

# New
POLICY_READER_SERVER_NAME = "policy.reader"
POLICY_PROPOSER_SERVER_NAME = "policy.proposer"
APPROVER_SERVER_NAME = "approver"
```

### Phase 5: Two-compositor architecture (future)

1. Create user compositor in `compositor_factory.py`
2. Mount `policy.reader` on both compositors
3. Mount `policy.proposer` on agent compositor only
4. Mount `approver` on user compositor only
5. Wire global `/mcp` endpoint to user compositor

## Files to Modify

- `adgn/src/adgn/mcp/approval_policy/engine.py` - Add hub, pending resource, decide tools
- `adgn/src/adgn/mcp/_shared/constants.py` - Rename constants
- `adgn/src/adgn/agent/runtime/container.py` - Remove approvals, simplify setup
- `adgn/src/adgn/agent/approvals.py` - Keep ApprovalHub, remove deprecated code
- `adgn/src/adgn/mcp/approvals/` - DELETE entire directory

## Files to Create

- `adgn/src/adgn/agent/mcp_bridge/compositor_factory.py` - User compositor (Phase 5)

## Testing

- Update `test_approval_integration.py` to use new tool names
- Update any tests referencing `approve_call`/`deny_abort` etc.
- Verify pending resource broadcasts correctly
