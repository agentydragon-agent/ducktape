# Wave 1.1.C: Policy State Management - Implementation Summary

## Overview
Implemented comprehensive policy state management including persistence, validation, reload, and versioning features.

## Files Modified

### 1. Database Schema (`src/adgn/agent/persist/sqlite.py`)
- **Added tables**:
  - `policies`: Stores named policies with metadata (id, text, description, enabled, timestamps)
  - `policy_history`: Tracks historical versions of policies (auto-saved on updates)

### 2. Persistence Layer (`src/adgn/agent/persist/__init__.py`)
- **New models**:
  - `Policy`: Main policy model with full metadata
  - `PolicyHistoryEntry`: Historical version tracking (internal implementation detail)

- **New API methods**:
  - `create_policy(policy_id, text, description, enabled)` → Policy
  - `get_policy(policy_id)` → Policy | None
  - `update_policy(policy_id, text, description)` → Policy
  - `list_policies(offset, limit)` → list[Policy]
  - `delete_policy(policy_id)` → None

### 3. SQLite Implementation (`src/adgn/agent/persist/sqlite.py`)
- Implemented all CRUD operations for policies
- Automatic history tracking on create/update
- CASCADE deletion of history when policy is deleted
- Pagination support for policy listing

### 4. MCP Server (`src/adgn/mcp/approval_policy/server.py`)
- **New tools in ApprovalPolicyAdminServer**:
  - `validate_policy(source)` → ValidationResult
    - Syntax validation (Python compile)
    - Runtime validation (self-check via Docker)
    - Returns detailed error messages
  - `reload_policy(source?)` → None
    - Reload from persistence (if source=None)
    - Reload from provided source (if source provided)
    - Validates before activation
    - Triggers resource notifications

- **New models**:
  - `ValidatePolicyArgs`: Input for validation
  - `ValidationResult`: Output with valid flag and error list
  - `ReloadPolicyArgs`: Input for reload operation

- **New resources** (added by user):
  - `resource://policies/list`: List all policies
  - `resource://policies/{policy_id}`: Get policy details

## Features Implemented

### 1. ✅ Policy Persistence
- SQLite schema with `policies` and `policy_history` tables
- Full CRUD operations through persistence API
- Automatic history tracking on every update
- Foreign key constraints and cascading deletes

### 2. ✅ Policy Reload
- Hot-reload from persistence without restarting
- Reload from provided source for testing
- Validation before activation
- Resource update notifications to clients

### 3. ✅ Policy Validation
- **Syntax validation**: Python `compile()` check for syntax errors
- **Runtime validation**: Docker-based self-check execution
- Detailed error messages with line numbers
- Non-destructive (validates without activating)

### 4. ✅ Policy Versioning
- Automatic history tracking on create and update
- Timestamps for created_at and updated_at
- History stored in separate table for clean separation
- Supports future rollback implementation

## SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS policies (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  description TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  policy_id TEXT NOT NULL,
  text TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT,
  FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_policy_history_policy ON policy_history(policy_id);
CREATE INDEX IF NOT EXISTS idx_policy_history_updated ON policy_history(updated_at);
```

## Tests

### Created Test Files
1. **`tests/agent/test_policy_state_management.py`** (10 tests, all passing):
   - `test_create_policy`: Basic policy creation
   - `test_get_policy`: Retrieval and non-existent handling
   - `test_update_policy`: Update with history tracking
   - `test_update_nonexistent_policy_raises`: Error handling
   - `test_list_policies`: Pagination support
   - `test_delete_policy`: Deletion
   - `test_policy_history_tracking`: Automatic history
   - `test_policy_enabled_flag`: Enable/disable support
   - `test_policy_description_optional`: Optional fields
   - `test_concurrent_policy_updates`: Concurrency handling

2. **`tests/agent/test_policy_validation_reload.py`** (7 tests, requires Docker):
   - `test_validate_policy_valid`: Valid policy validation
   - `test_validate_policy_syntax_error`: Syntax error detection
   - `test_validate_policy_runtime_error`: Runtime validation
   - `test_reload_policy_from_persistence`: Reload from DB
   - `test_reload_policy_from_source`: Reload from provided source
   - `test_reload_policy_validates_source`: Validation on reload
   - `test_reload_policy_no_persistence_raises`: Error handling

### Test Results
```
✅ 10/10 policy state management tests passing
✅ All type checking (mypy) passing
✅ All linting (ruff) passing
✅ No import errors or undefined names
```

## API Examples

### Creating a Policy
```python
policy = await persistence.create_policy(
    policy_id="strict-approval",
    text="# Always require approval\nreturn {'decision': 'ask'}",
    description="Requires manual approval for all actions",
    enabled=True,
)
```

### Validating a Policy
```python
result = await admin_server.validate_policy(
    ValidatePolicyArgs(source="print('test')")
)
# result.valid == True, result.errors == []
```

### Reloading from Persistence
```python
await admin_server.reload_policy(ReloadPolicyArgs(source=None))
# Engine now has the latest policy from database
```

## Design Decisions

1. **Separate history table**: Keeps current policy clean, allows efficient queries
2. **Automatic history**: No manual tracking needed, every change is recorded
3. **Validation before activation**: Prevents broken policies from being deployed
4. **Two-level validation**: Syntax check first (fast), then Docker check (thorough)
5. **Pagination**: Prevents memory issues with large policy libraries
6. **Optional rollback**: History table supports rollback, but not exposed yet (future work)

## Definition of Done ✅

- [x] Policies table created in SQLite
- [x] Policy CRUD operations in persistence layer
- [x] Reload resource implemented
- [x] Validation added (syntax + runtime)
- [x] Tests pass for all state management features
- [x] Type checking (mypy) passes
- [x] Linting (ruff) passes
- [x] History tracking implemented
- [x] Documentation provided

## Future Enhancements

1. **Rollback API**: Expose `rollback_policy(policy_id, history_id)` through MCP
2. **Diff views**: Show what changed between policy versions
3. **Policy templates**: Pre-built policy templates for common scenarios
4. **Policy search**: Full-text search across policy text and descriptions
5. **Policy groups**: Organize policies into logical groups
6. **Audit log**: Track who made what changes when
