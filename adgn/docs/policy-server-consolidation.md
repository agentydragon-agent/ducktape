# Policy Server Consolidation Plan

## Goal

Consolidate policy and approval handling into a single `PolicyEngine` class that owns all policy-related servers, state, and middleware.

## Status

| Phase | Status |
|-------|--------|
| Phase 1-3: Core consolidation | ✅ Done |
| Phase 4: Rename constants | ⏳ Partial |
| Phase 5: Two-compositor architecture | ❌ Future |
| Test migration | ⏳ Partial |

## Completed

- `_ApprovalHub` and `_PolicyGatewayMiddleware` moved into `engine.py` as private classes
- `pending://calls` resource added to reader (hub changes trigger broadcast)
- `decide_call(call_id, decision: CallDecision)` and `decide_proposal(proposal_id, decision: ProposalDecision)` tools on admin server
- Deleted `mcp/approvals/` and `mcp/policy_gateway/` directories
- `container.py` simplified: uses `engine.gateway`, no separate hub/gateway fields
- `runtime.py` no longer accesses PolicyEngine internal state; UI reads `pending://calls` directly
- Type annotations fixed (`AgentID`, `Persistence`, `ServerBus`)
- Test fixtures: `make_pg_client` (yields client) and `make_pg_compositor` (yields client, comp, engine)

## Remaining

### Test migration (10 files using old `make_pg_session` fixture)

```
tests/mcp/test_pg_middleware.py
tests/agent/ui/test_ui_agent_integration.py
tests/agent/test_mcp_resources_flow.py
tests/agent/test_runtime_timeout.py
tests/agent/test_tool_error_*.py
tests/agent/test_policy_eval_abort_on_error.py
tests/mcp/compositor/test_meta_basic.py
tests/mcp/compositor/test_admin_pinned_detach.py
tests/props/test_lint_issue_bootstrap.py
```

Pattern: `make_pg_session(...)` → `make_pg_client(...)` or `make_pg_compositor(...)`
Pattern: `approval_hub.resolve(call_id, ...)` → `admin.call_tool("decide_call", {"call_id": ..., "decision": ...})`

### Cleanup

- Remove deprecated `ApprovalHub`/`ApprovalPolicyEngine` from `adgn/agent/approvals.py`
- Remove old `APPROVAL_POLICY_SERVER_NAME*` constants
