# Policy Server Consolidation Plan

## Goal

Consolidate policy and approval handling into a single `PolicyEngine` class that owns all policy-related servers, state, and middleware.

## Status

| Phase | Status |
|-------|--------|
| Phase 1-3: Core consolidation | ✅ Done |
| Phase 4: Cleanup deprecated code | ✅ Done |
| Phase 5: Two-compositor architecture | ❌ Future |

## Completed

### Phase 1-3: Core Consolidation

- `_ApprovalHub` and `_PolicyGatewayMiddleware` moved into `engine.py` as private classes
- `pending://calls` resource added to reader (hub changes trigger broadcast)
- `decide_call` and `decide_proposal` tools on admin server
- Deleted `mcp/approvals/` and `mcp/policy_gateway/` directories
- `container.py` simplified: uses `engine.gateway`
- `runtime.py` no longer accesses PolicyEngine internal state
- Test fixtures migrated: `pg_client`, `make_pg_client`, `make_pg_compositor`, `make_decision_engine`

### Phase 4: Cleanup Deprecated Code

- Removed `ApprovalPolicyEngine` class and related fixtures from tests
- Removed `ApprovalHub` class (now `_ApprovalHub` private in engine.py)
- Removed deprecated `make_policy_engine` factory function
- Updated `approvals.py` to only export: `ApprovalRequest`, `ApprovalToolCall`, `WellKnownTools`, `load_default_policy_source`
- Simplified constants: removed `APPROVAL_POLICY_SERVER_NAME_READER/_PROPOSER/_APPROVER`
- Added new constants: `POLICY_PROPOSER_SERVER_NAME`, `POLICY_ADMIN_SERVER_NAME`
- Added `docker_client` fixture to `tests/conftest.py`
- Renamed `stub_approval_policy_engine` fixture to `stub_policy_engine`

## Future: Phase 5 Two-Compositor Architecture

Separate agent-facing and user-facing compositors:
- Agent compositor: `reader`, `policy_proposer`, gateway middleware
- User compositor: `reader`, `admin`
- Global `/mcp` endpoint routes to user compositor
