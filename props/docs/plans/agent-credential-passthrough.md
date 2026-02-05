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

### Explicit Naming Convention

**Critical**: Admin vs agent DB access must be obvious in code. Variable names, function names, and dependencies should clearly indicate which credentials are used.

- `get_admin_db` - Admin connection pool (explicit admin access)
- `get_agent_db` - Agent credentials when available, raises for anonymous

Rename existing `get_db` → `get_admin_db` to make admin access explicit.

### New Dependencies

```python
# props/backend/deps.py

def get_admin_db(request: Request) -> Database:
    """Get admin Database instance from app state.

    Uses the server's admin connection pool. Use only for operations
    that genuinely require admin privileges (INSERT into llm_requests,
    launching agent runs, etc).
    """
    return request.app.state.db


def get_agent_db(request: Request) -> Database:
    """Get Database using agent credentials for RLS enforcement.

    For agent callers: Creates Database with agent's Postgres credentials.
    For admin callers: Returns admin Database instance.
    For anonymous: Raises 401.
    """
    auth: AuthContext | None = request.state.auth

    if auth is None or not auth.is_authenticated:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Admin users get admin connection
    if auth.is_admin:
        return request.app.state.db

    # Agent users get their own connection - credentials guaranteed present for agents
    if not auth.username or not auth.password:
        raise HTTPException(status_code=500, detail="Agent auth missing credentials")
    agent_config = DatabaseConfig(
        host=request.app.state.db.config.host,
        port=request.app.state.db.config.port,
        database=request.app.state.db.config.database,
        username=auth.username,
        password=auth.password,
    )
    return Database(agent_config)
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
- Stats/overview endpoints - useful for critic dev agents to see metrics

**Use `get_admin_db` (explicit admin access):**

- LLM proxy (`/api/llm/v1/responses`) - needs to INSERT into `llm_requests` as admin (proxy pattern)
- Agent definition push - needs INSERT permission that agents don't have
- Eval API - launches agent runs, needs admin
- Ground truth endpoints - admin-only dashboard

### Migration Path

1. **Phase 1: Rename `get_db` → `get_admin_db` and add `get_agent_db`** ✅
   - ✅ Rename existing `get_db` to `get_admin_db` in `deps.py`
   - ✅ Add `AdminDb` type alias for FastAPI route signatures
   - ✅ Update all imports and usages to `get_admin_db` (no behavior change)
   - ✅ Add new `get_agent_db` dependency (in `auth.py` to avoid circular deps with `deps.py`)
   - ✅ Add `AgentDb` type alias in `auth.py`
   - ✅ Add `_per_request` mode to `Database` (NullPool, no verification)

2. **Phase 2: Migrate read-heavy endpoints to `get_agent_db`** ✅
   - ✅ `agent_definitions.py`: `list_definitions` → `AgentDb`
   - ✅ `stats.py`: all endpoints → `AgentDb`
   - ✅ `runs.py` read endpoints: `list_active_runs`, `list_runs`, `get_run`, `get_run_llm_requests` → `AgentDb`
   - ✅ `runs.py` write endpoints: `trigger_validation_runs` keeps `AdminDb` with explicit `require_admin_access`
   - ✅ `runs.py` admin-only: `list_jobs` keeps explicit `require_admin_access`
   - ✅ Unit tests for `get_agent_db` in `props/backend/test_auth.py`

3. **Phase 3: Migrate write endpoints with RLS**
   - ⬚ Grading edges endpoints (when they exist)
   - ⬚ Reported issues endpoints (when they exist)
   - ⬚ Remove manual ACL checks that RLS now handles

4. **Phase 4: Clean up**
   - ⬚ Remove `ACL_CAN_*` sets for operations now handled by RLS
   - ⬚ Simplify `CallerType` checks
   - ⬚ Update tests

### Files Requiring Update

All routes now use `get_admin_db`. Decide which should become `get_agent_db`:

**`agent_definitions.py`** (1 usage)

- `list_definitions` → `get_agent_db` (SELECT allowed by RLS)

**`llm.py`** (1 usage)

- `responses` → `get_admin_db` (proxy needs admin INSERT)

**`ground_truth.py`** (4 usages)

- All endpoints → `get_admin_db` (admin-only dashboard)

**`runs.py`** (5 usages)

- `list_active_runs` → `get_agent_db` (RLS filters)
- `get_run` → `get_agent_db` (RLS enforces access)
- `get_run_llm_requests` → `get_agent_db` (RLS filters)
- `start_validation_run` → `get_admin_db` (launches runs)
- `create_grading_edges` → `get_agent_db` (RLS enforces grader ownership)

**`registry.py`** (1 usage)

- `push_manifest` → `get_admin_db` (needs INSERT permission)

**`stats.py`** (3 usages)

- All endpoints → `get_agent_db` (useful for critic dev)

**`eval.py`** (2 usages)

- All endpoints → `get_admin_db` (launches agent runs)

### Endpoints to Migrate

| Endpoint                     | Current Dep       | Target Dep     | Notes                         |
| ---------------------------- | ----------------- | -------------- | ----------------------------- |
| `GET /api/runs`              | `get_admin_db`    | `get_agent_db` | RLS filters visible runs      |
| `GET /api/runs/{id}`         | `get_admin_db`    | `get_agent_db` | RLS enforces access           |
| `POST /api/runs/{id}/grades` | `get_admin_db`    | `get_agent_db` | RLS enforces grader ownership |
| `POST /api/runs/{id}/issues` | `get_admin_db`    | `get_agent_db` | RLS enforces critic ownership |
| `GET /api/stats/*`           | `get_admin_db`    | `get_agent_db` | RLS filters visible data      |
| `POST /api/llm/v1/responses` | ✅ `get_admin_db` | `get_admin_db` | Proxy needs admin INSERT      |
| `POST /api/eval/*`           | ✅ `get_admin_db` | `get_admin_db` | Launches runs as admin        |
| `POST /api/registry/*`       | ✅ `get_admin_db` | `get_admin_db` | Definition push needs admin   |
| `GET /api/ground_truth/*`    | ✅ `get_admin_db` | `get_admin_db` | Admin-only                    |
| `GET /api/definitions`       | `get_admin_db`    | `get_agent_db` | SELECT is allowed by RLS      |

### RLS Policy Gaps

Review existing RLS policies for gaps:

1. **`agent_runs`**: Policies support recursive visibility:
   - `agent_runs_select_own`: See own run
   - `agent_runs_select_descendants`: See all descendants via `is_agent_ancestor(current_agent_run_id(), agent_run_id)`
   - `agent_runs_agent_select`: Type-specific access (PO sees critics/graders on train, etc.)

   Migration `20260203000000_recursive_agent_visibility.py` replaces the old direct-children policy with recursive descendant visibility.

2. **`llm_requests`**: Current INSERT policy requires `current_agent_run_id() = agent_run_id`. This conflicts with proxy pattern where backend inserts on behalf of agent. **Keep admin connection for LLM proxy.**

3. **`agent_definitions`**: INSERT requires admin or PO/improvement agent type. The RLS policy should handle this correctly.

4. **Stats views**: Views like `recall_by_definition_example`, `recall_by_run` are granted SELECT to `agent_base`. These aggregate data but RLS on underlying tables (agent_runs, grading_edges) should filter appropriately.

### Benefits

1. **Single source of truth**: RLS policies define access control, not Python code
2. **Defense in depth**: Even if Python ACL check is wrong, RLS prevents unauthorized access
3. **Simpler code**: Remove redundant `CallerType` checks for RLS-protected operations
4. **Audit trail**: Database logs show actual user performing operations

### Risks and Mitigations

| Risk                            | Mitigation                                                |
| ------------------------------- | --------------------------------------------------------- |
| Connection overhead             | Start with per-request connections; add pooling if needed |
| RLS policy gaps                 | Audit policies before migration; add missing policies     |
| Breaking existing functionality | Gradual migration, one endpoint at a time                 |

Note: RLS errors can be exposed directly - agents knowing schema/policies is acceptable.

### Testing Strategy

1. **Unit tests**: Test `get_agent_db` returns correct Database for each auth context
2. **Integration tests**: Test endpoint access with different agent types
3. **RLS tests**: Verify RLS policies work as expected via SQL
4. **Negative tests**: Verify unauthorized access is denied

## Future: Frontend Authentication

For symmetry, the frontend dashboard could also authenticate to the backend instead of relying on localhost admin access. This would:

- Enable remote dashboard access (not just localhost)
- Provide consistent auth model across all clients
- Allow per-user audit trails in database logs

### Current State

Frontend relies on `PROPS_ALLOW_LOCALHOST_ADMIN=true` — requests from localhost with no credentials get admin access. This only works when accessing from the same machine.

### Options for Frontend Auth

**Option A: Credentials endpoint**

Backend serves admin credentials at a protected endpoint (e.g., `/api/auth/credentials`). Frontend fetches on load and uses for subsequent requests.

```typescript
// On app init
const { username, password } = await fetch("/api/auth/credentials").then((r) => r.json());
// Store in memory, use for all API calls
```

Pros: Simple, credentials not in bundle
Cons: Initial fetch adds latency, credentials endpoint needs protection

**Option B: Baked into JS at build time**

Bazel genrule injects credentials into the frontend bundle during build.

```python
# BUILD.bazel
genrule(
    name = "frontend_with_creds",
    srcs = [":frontend_bundle"],
    outs = ["frontend_bundle_with_creds.js"],
    cmd = "sed 's/__ADMIN_USER__/$(ADMIN_USER)/' ... > $@",
)
```

Pros: No extra fetch, works offline
Cons: Credentials in bundle (inspect-able), rebuild needed to rotate

**Option C: Session-based auth with login**

Add login endpoint, issue session cookie, validate on requests.

Pros: Standard web auth pattern, supports multiple users
Cons: More complex, need session storage, login UI

**Option D: Environment variable injection at serve time**

Backend injects credentials into HTML template when serving the SPA.

```html
<script>
  window.__PROPS_AUTH__ = { user: "{{user}}", pass: "{{pass}}" };
</script>
```

Pros: No rebuild needed, credentials not in static bundle
Cons: Requires templated serving, credentials visible in page source

### Recommendation

Start with **Option A (credentials endpoint)** — simplest to implement, keeps credentials out of static bundle. The endpoint can be protected by requiring localhost or a bootstrap token.

For production with remote access, consider **Option C (session auth)** later.

## Non-Goals

- Connection pooling per agent (can add later if needed)
- Changing RLS policies (use existing policies)
- Removing admin connection pool (always needed for admin-only operations)

## Open Questions

1. Should we cache agent Database instances? Start simple, optimize later.

## Implementation Order

1. ✅ Rename `get_db` → `get_admin_db`, add `AdminDb` type alias
2. ✅ Add `get_agent_db` dependency (in `auth.py`, with `_per_request` Database mode)
3. ✅ Add unit tests for `get_agent_db` (`props/backend/test_auth.py`)
4. ✅ Migrate read endpoints (`agent_definitions`, `stats`, `runs` reads) to `AgentDb`
5. ⬚ Add integration test for agent credential passthrough (e2e with real Postgres)
6. ⬚ Migrate write endpoints with RLS (grading edges, reported issues - when they exist)
7. ⬚ Remove redundant Python ACL checks
8. ⬚ Update documentation
