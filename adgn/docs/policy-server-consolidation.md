# Policy Server Consolidation Plan

## Goal

Consolidate policy and approval handling into a single `PolicyEngine` class that owns all policy-related servers, state, and middleware.

## Current State

### Servers (mounted names)
| Name | Type | Purpose |
|------|------|---------|
| `approval_policy` | NotifyingFastMCP | Policy evaluation, resources |
| `approval_policy.proposer` | FastMCP | Policy change proposals |
| `approval_policy.approver` | FastMCP | Policy admin (NOT mounted, private client) |
| `approvals` | NotifyingFastMCP | Tool call approval actions |

### Problems
1. **Fragmented ownership**: ApprovalHub, PolicyEngine, PolicyGatewayMiddleware created separately in container.py
2. **Redundant servers**: `approvals` separate from policy servers despite being same flow
3. **Private client hack**: `approval_policy.approver` not mounted, accessed via weird private client
4. **Fragmented tools**: `approve_call`, `deny_abort`, `deny_continue` as separate tools
5. **Inconsistent naming**: `approval_policy` vs `approvals`, mixed prefixes

## Target Architecture

### PolicyEngine: Single Owner

```python
class PolicyEngine:
    """Complete policy subsystem - servers, state, and middleware."""

    # === Servers (3) ===
    reader: NotifyingFastMCP      # evaluate_policy, policy resources, pending://calls
    policy_proposer: FastMCP      # propose/withdraw policy changes
    admin: FastMCP                # decide_call, decide_proposal, set_policy

    # === Internal State ===
    _hub: _ApprovalHub            # futures for pending calls (private)
    _gateway: PolicyGatewayMiddleware

    @property
    def gateway(self) -> PolicyGatewayMiddleware:
        """Middleware to install on agent compositor."""
        return self._gateway
```

Note: `_ApprovalHub` becomes a private implementation detail inside PolicyEngine, not a separate public class.

### Two Compositors
1. **Agent compositor**: What the agent's MCP client connects to (policy-gated)
2. **User compositor**: What the user/UI connects to (admin capabilities)

### Three Servers

| Mount Name | Type | Mounted On | Purpose |
|------------|------|------------|---------|
| `reader` | NotifyingFastMCP | agent + user | Read policy, evaluate, view pending |
| `policy_proposer` | FastMCP | agent | Propose policy changes |
| `admin` | FastMCP | user only | Approve/deny calls and proposals |

### Resource URIs

| URI | Server | Description |
|-----|--------|-------------|
| `policy://source` | reader | Current policy source code |
| `policy://proposals` | reader | Policy change proposals index |
| `policy://proposals/{id}` | reader | Individual proposal |
| `pending://calls` | reader | Pending tool call approvals |

Note: `pending://` not `policy://` for pending calls - they're runtime state, not policy definitions.

### Tools

#### reader
- `evaluate_policy(name, arguments)` - Evaluate policy for a tool call

#### policy_proposer
- `propose_policy_change(content)` - Create a policy change proposal
- `withdraw_proposal(id)` - Withdraw own proposal

#### admin
- `decide_call(call_id, decision: CallDecision)` - Approve/deny a pending tool call
  ```python
  class CallDecision(str, Enum):
      APPROVE = "approve"           # Allow the call
      DENY_ABORT = "deny_abort"     # Deny and abort turn
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

1. **Move ApprovalHub into PolicyEngine**
   - Make `_ApprovalHub` a private class inside `engine.py`
   - PolicyEngine creates hub in `__init__`
   - No public `ApprovalHub` class - it's an implementation detail

2. **Move PolicyGatewayMiddleware into PolicyEngine**
   - PolicyEngine creates middleware in `__init__`
   - Expose via `engine.gateway` property
   - Middleware uses engine's internal hub directly

3. **Add pending://calls resource to reader**
   - Resource returns hub's pending requests
   - Hub change → reader broadcasts `pending://calls` update
   - Wiring is internal to PolicyEngine

4. **Add decide_call tool to admin server**
   - Create `CallDecision` enum: `APPROVE`, `DENY_ABORT`, `DENY_CONTINUE`
   - Single `decide_call(call_id, decision)` tool
   - Calls internal `_hub.resolve()` with appropriate decision type

5. **Consolidate decide_proposal tool**
   - Create `ProposalDecision` enum: `APPROVE`, `REJECT`
   - Replace `approve_proposal`/`reject_proposal` with `decide_proposal(id, decision)`

### Phase 2: Delete approvals module

1. Delete `adgn/mcp/approvals/` directory entirely
2. Remove `attach_approvals` call from container.py
3. Remove `APPROVALS_SERVER_NAME` constant
4. Remove `ApprovalHub` from `adgn/agent/approvals.py` (now private in engine)

### Phase 3: Simplify container.py

Container setup becomes:
```python
engine = PolicyEngine(agent_id=..., persistence=..., docker_client=..., policy_source=...)

# Mount servers
comp.mount_inproc("reader", engine.reader)
comp.mount_inproc("policy_proposer", engine.policy_proposer)
# admin mounted on user compositor (later)

# Install middleware
comp.add_middleware(engine.gateway)
```

Remove:
- `approval_hub: ApprovalHub` field (now internal to engine)
- `_policy_reader` / `_policy_approver` stub fields (use engine properties)
- `_policy_gateway` field (use `engine.gateway`)
- Private client setup for approver
- `attach_approvals` call

### Phase 4: Rename constants

```python
# Old
APPROVAL_POLICY_SERVER_NAME = "approval_policy"
APPROVAL_POLICY_SERVER_NAME_READER = "approval_policy"
APPROVAL_POLICY_SERVER_NAME_PROPOSER = "approval_policy.proposer"
APPROVAL_POLICY_SERVER_NAME_APPROVER = "approval_policy.approver"

# New
READER_SERVER_NAME = "reader"
POLICY_PROPOSER_SERVER_NAME = "policy_proposer"
ADMIN_SERVER_NAME = "admin"
```

### Phase 5: Two-compositor architecture (future)

1. Create user compositor in `compositor_factory.py`
2. Mount `reader` on both compositors
3. Mount `policy_proposer` on agent compositor only
4. Mount `admin` on user compositor only
5. Wire global `/mcp` endpoint to user compositor

## Files to Modify

- `adgn/src/adgn/mcp/approval_policy/engine.py` - Add hub, gateway, pending resource, decide tools
- `adgn/src/adgn/mcp/_shared/constants.py` - Rename constants
- `adgn/src/adgn/agent/runtime/container.py` - Massive simplification
- `adgn/src/adgn/agent/approvals.py` - Remove ApprovalHub (move to engine.py)

## Files to Delete

- `adgn/src/adgn/mcp/approvals/` - Entire directory
- `adgn/src/adgn/mcp/policy_gateway/` - Move middleware into engine.py

## Files to Create

- `adgn/src/adgn/agent/mcp_bridge/compositor_factory.py` - User compositor (Phase 5)

## Testing

- Update `test_approval_integration.py` to use new tool names
- Update any tests referencing `approve_call`/`deny_abort` etc.
- Update tests that create `ApprovalHub` directly (use engine instead)
- Verify pending resource broadcasts correctly
