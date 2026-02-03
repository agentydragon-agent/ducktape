# Design: Agent Credential Passthrough for Backend Requests

## Summary

When an agent authenticates to the backend with their Postgres credentials (`agent_{uuid}`), use those credentials for the database connection instead of the admin connection pool. This leverages PostgreSQL RLS policies directly, removing the need to duplicate access control logic in Python.

## Current State

1. **Authentication**: Agents authenticate via HTTP Basic Auth with username `agent_{uuid}` and HMAC-derived password
2. **Connection**: Backend validates credentials against Postgres (connection test), then uses a single admin connection pool (`app.state.db`) for all database operations
3. **ACL Enforcement**: Python code checks `CallerType` and enforces permissions manually
4. **RLS Policies**: Exist in database for `agent_base` role but are unused since backend connects as admin

## Proposed State

1. **Agent requests**: Use agent's Postgres credentials for the database connection
2. **Admin requests**: Continue using admin connection pool
3. **RLS Enforcement**: Postgres RLS policies automatically enforce access control
4. **Simplified Python**: Remove redundant ACL checks that RLS already handles

## Design

### New Dependency: `get_agent_db`

```python
# props/backend/deps.py

def get_agent_db(request: Request) -> Database:
    """Get Database instance using agent credentials if available.

    For agent callers: Creates a Database instance using the agent's
    Postgres credentials, enabling RLS policy enforcement.

    For admin/anonymous callers: Returns the admin Database instance.
    """
    auth: AuthContext = getattr(request.state, "auth", None)

    # Use agent credentials if authenticated as agent
    if auth and auth.is_authenticated and not auth.is_admin:
        assert auth.username and auth.password
        agent_config = DatabaseConfig(
            host=request.app.state.db.config.host,
            port=request.app.state.db.config.port,
            database=request.app.state.db.config.database,
            username=auth.username,
            password=auth.password,
        )
        return Database(agent_config)

    # Fall back to admin connection
    return request.app.state.db
```

### Connection Lifecycle

**Option A: Per-request connections (simple, start here)**

- Create new `Database` instance for each agent request
- Connection opened/closed within the request context manager
- No pooling for agent connections

**Option B: Connection pool per agent (optimization, later)**

- Cache `Database` instances keyed by `agent_run_id`
- Requires lifecycle management (eviction, cleanup)
- Only implement if Option A has performance issues

### Endpoint Classification

**Use `get_agent_db` (agent credentials):**

- Most read endpoints where RLS applies
- `grading_edges` writes (RLS already enforces `is_own_run_as(grader_run_id, 'grader')`)
- `reported_issues` writes (RLS enforces `is_own_run_as(agent_run_id, 'critic')`)

**Continue using `get_db` (admin credentials):**

- LLM proxy (`/api/llm/v1/responses`) - needs to INSERT into `llm_requests` as admin (proxy pattern)
- Agent definition push - needs INSERT permission that agents don't have
- Eval API - launches agent runs, needs admin
- Stats/overview endpoints - admin-only dashboard routes

### Migration Path

1. **Phase 1: Add `get_agent_db` dependency**
   - Implement `get_agent_db` in `deps.py`
   - Keep both dependencies available
   - No behavior change yet

2. **Phase 2: Migrate read-heavy endpoints**
   - Update routes that only read data accessible to agents
   - Replace `db: Annotated[Database, Depends(get_db)]` with `db: Annotated[Database, Depends(get_agent_db)]`
   - Routes: runs list/detail (read-only parts), stats views

3. **Phase 3: Migrate write endpoints with RLS**
   - Grading edges endpoints
   - Reported issues endpoints
   - Remove manual ACL checks that RLS now handles

4. **Phase 4: Clean up**
   - Remove `ACL_CAN_*` sets for operations now handled by RLS
   - Simplify `CallerType` checks
   - Update tests

### Endpoints to Migrate

| Endpoint                     | Current Dep | Target Dep     | Notes                         |
| ---------------------------- | ----------- | -------------- | ----------------------------- |
| `GET /api/runs`              | `get_db`    | `get_agent_db` | RLS filters visible runs      |
| `GET /api/runs/{id}`         | `get_db`    | `get_agent_db` | RLS enforces access           |
| `POST /api/runs/{id}/grades` | `get_db`    | `get_agent_db` | RLS enforces grader ownership |
| `POST /api/runs/{id}/issues` | `get_db`    | `get_agent_db` | RLS enforces critic ownership |
| `GET /api/stats/*`           | `get_db`    | Keep `get_db`  | Admin-only dashboard          |
| `POST /api/llm/v1/responses` | `get_db`    | Keep `get_db`  | Proxy needs admin INSERT      |
| `POST /api/eval/*`           | `get_db`    | Keep `get_db`  | Launches runs as admin        |
| `POST /api/registry/*`       | `get_db`    | Keep `get_db`  | Definition push needs admin   |
| `GET /api/ground_truth/*`    | `get_db`    | Keep `get_db`  | Admin-only                    |
| `GET /api/definitions`       | `get_db`    | `get_agent_db` | SELECT is allowed by RLS      |

### RLS Policy Gaps

Review existing RLS policies for gaps:

1. **`agent_runs`**: Current policy allows SELECT on own run + children + parent chain. May need to add policy for PO/improvement agents to see all their spawned runs.

2. **`llm_requests`**: Current INSERT policy requires `current_agent_run_id() = agent_run_id`. This conflicts with proxy pattern where backend inserts on behalf of agent. **Keep admin connection for LLM proxy.**

3. **`agent_definitions`**: INSERT requires admin or PO/improvement agent type. The RLS policy should handle this correctly.

### Benefits

1. **Single source of truth**: RLS policies define access control, not Python code
2. **Defense in depth**: Even if Python ACL check is wrong, RLS prevents unauthorized access
3. **Simpler code**: Remove redundant `CallerType` checks for RLS-protected operations
4. **Audit trail**: Database logs show actual user performing operations

### Risks and Mitigations

| Risk                              | Mitigation                                                       |
| --------------------------------- | ---------------------------------------------------------------- |
| Connection overhead               | Start with per-request connections; add pooling if needed        |
| RLS policy gaps                   | Audit policies before migration; add missing policies            |
| Breaking existing functionality   | Gradual migration, one endpoint at a time                        |
| Error messages expose RLS details | Catch and wrap RLS permission errors with user-friendly messages |

### Testing Strategy

1. **Unit tests**: Test `get_agent_db` returns correct Database for each auth context
2. **Integration tests**: Test endpoint access with different agent types
3. **RLS tests**: Verify RLS policies work as expected via SQL
4. **Negative tests**: Verify unauthorized access is denied

## Non-Goals

- Connection pooling per agent (can add later if needed)
- Changing RLS policies (use existing policies)
- Removing admin connection pool (always needed for admin-only operations)

## Open Questions

1. Should we cache agent Database instances? Start simple, optimize later.
2. Should `get_agent_db` raise on anonymous? Or return admin db? (Leaning toward raising)
3. How to handle RLS errors gracefully in API responses?

## Implementation Order

1. Add `get_agent_db` dependency (no behavior change)
2. Add integration test for agent credential passthrough
3. Migrate one read endpoint as proof of concept
4. Migrate remaining read endpoints
5. Migrate write endpoints with RLS
6. Remove redundant Python ACL checks
7. Update documentation
