# Policy Server Consolidation Plan

## Status: Complete

All phases implemented.

| Phase | Status |
|-------|--------|
| Phase 1-3: Core consolidation | ✅ Done |
| Phase 4: Cleanup deprecated code | ✅ Done |
| Phase 5: Two-compositor architecture | ✅ Done |

## Summary

### Phase 1-3: Core Consolidation
- `_ApprovalHub` and `_PolicyGatewayMiddleware` moved into `engine.py`
- `pending://calls` resource, `decide_call`/`decide_proposal` tools
- Deleted `mcp/approvals/` and `mcp/policy_gateway/`

### Phase 4: Cleanup
- Removed deprecated `ApprovalPolicyEngine`, `ApprovalHub`, `make_policy_engine`
- Simplified exports and constants

### Phase 5: Two-Compositor Architecture
Single `/mcp` endpoint with token-based routing:
- **User tokens** → global compositor (sees all agents)
- **Agent tokens** → agent compositor (policy-gated)

Key files:
- `mcp_bridge/auth.py` - `TokenRoutingASGI`, `load_tokens()`
- `mcp_bridge/registry.py` - `InfrastructureRegistry`
- `mcp_bridge/servers/agents.py` - agent management (list/create/delete/boot)
- `mcp_bridge/servers/agent_control.py` - `send_prompt`/`abort_run` (internal agents only)

External agents: no `agent_control` server → user can only view/approve, not control.

Frontend: MCP-only (no REST API). Token from URL query param.
