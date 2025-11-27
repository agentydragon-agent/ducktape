# Policy Server Consolidation Plan

## Goal

Consolidate policy and approval handling into a single `PolicyEngine` class that owns all policy-related servers, state, and middleware.

## Status

| Phase | Status |
|-------|--------|
| Phase 1-3: Core consolidation | ✅ Done |
| Phase 4: Cleanup deprecated code | ⏳ Next |
| Phase 5: Two-compositor architecture | ❌ Future |

## Completed

- `_ApprovalHub` and `_PolicyGatewayMiddleware` moved into `engine.py` as private classes
- `pending://calls` resource added to reader (hub changes trigger broadcast)
- `decide_call` and `decide_proposal` tools on admin server
- Deleted `mcp/approvals/` and `mcp/policy_gateway/` directories
- `container.py` simplified: uses `engine.gateway`
- `runtime.py` no longer accesses PolicyEngine internal state
- Test fixtures migrated: `pg_client`, `make_pg_client`, `make_pg_compositor`, `make_decision_engine`

## Remaining: Phase 4 Cleanup

### 1. Remove deprecated `ApprovalPolicyEngine` class

File: `adgn/agent/approvals.py`

Still used by:
- `tests/conftest.py`: `make_policy_engine`, `approval_engine` fixtures
- `tests/agent/conftest.py`: `policy_evaluator` fixture
- `tests/agent/server/test_snapshot_proposals_invalid.py`: direct usage

Action: Migrate these to use `PolicyEngine` from `mcp/approval_policy/engine.py`

### 2. Remove deprecated `ApprovalHub` class

File: `adgn/agent/approvals.py`

No longer used externally (hub is now private `_ApprovalHub` in engine.py)

Action: Delete class after confirming no imports

### 3. Rename/remove old constants

File: `adgn/mcp/_shared/constants.py`

```python
# Old (to remove/rename):
APPROVAL_POLICY_SERVER_NAME = "approval_policy"
APPROVAL_POLICY_SERVER_NAME_READER = ...
APPROVAL_POLICY_SERVER_NAME_PROPOSER = ...
APPROVAL_POLICY_SERVER_NAME_APPROVER = ...
```

Used by:
- `agent/runtime/auto_attach.py`: `DEFAULT_AUTO_SERVER_NAMES`
- `mcp/approval_policy/clients.py`: `READER_SERVER_NAME`, `APPROVER_SERVER_NAME`

Action: Update usages to use new names, then remove old constants

## Future: Phase 5 Two-Compositor Architecture

Separate agent-facing and user-facing compositors:
- Agent compositor: `reader`, `policy_proposer`, gateway middleware
- User compositor: `reader`, `admin`
- Global `/mcp` endpoint routes to user compositor
