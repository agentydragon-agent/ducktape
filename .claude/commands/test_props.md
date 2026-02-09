# Test Props E2E

Run end-to-end props testing with a real OpenAI API key. Starts infrastructure,
initializes the database, runs the backend, pushes agent images, and tests
critic, grader, improver, and optimizer workflows.

## Usage

```bash
/test_props [workflow]
```

**Default (no argument):** Run the full setup and test all workflows.

**Examples:**

- `/test_props` - Full setup + test all workflows
- `/test_props critic` - Run a critic on a snapshot and verify output
- `/test_props grader` - Verify graders are running and grading
- `/test_props improver` - Test improver agent
- `/test_props setup` - Only set up infrastructure (no tests)

## Prerequisites

- `OPENAI_API_KEY` must be set in environment
- Podman must be running (claude_hooks handles this)
- Specimens repo at `/home/user/specimens`

## Procedure

### Phase 1: Infrastructure Setup

1. Check if podman containers `props-postgres` and `props-registry` are running:

   ```bash
   podman ps --format "{{.Names}}"
   ```

   If not running, start them:

   ```bash
   bash props/start_infra_podman.sh
   ```

2. Set environment variables:

   ```bash
   export PGHOST=127.0.0.1
   export PGPORT=5433
   export PGUSER=postgres
   export PGPASSWORD=$(cat props/.devenv/state/pg_password)
   export PGDATABASE=eval_results
   export ADGN_PROPS_SPECIMENS_ROOT=/home/user/specimens
   ```

3. Initialize database if needed (check if `snapshots` table has rows):
   ```bash
   bazel run //props/cli:cli -- db upgrade
   bazel run //props/cli:cli -- gt sync
   ```
   If specimen data has validation errors, move the problematic specimen
   directories out of `/home/user/specimens` and re-run `gt sync`.

### Phase 2: Start Backend

1. Check if backend is already running:
   ```bash
   curl -s http://127.0.0.1:8000/health
   ```
   If not running, start it:
   ```bash
   export PROPS_CONFIG_FILE=props/config.podman.toml
   export PROPS_REGISTRY_HOST=127.0.0.1
   export PROPS_REGISTRY_PORT=8000
   export PROPS_REGISTRY_UPSTREAM_URL=http://127.0.0.1:5050
   export PROPS_DOCKER_NETWORK=host
   bazel run //props/backend:backend_cli -- serve --host 127.0.0.1 --port 8000
   ```
   Run the backend in the background.

### Phase 3: Push Agent Images

Push images to the **registry proxy** (port 8000), not the direct registry
(port 5050). The proxy records agent definitions and the grader supervisor
listens for grader tag changes.

```bash
ADMIN_AUTH="postgres:$(cat props/.devenv/state/pg_password)"
```

For each agent type needed (critic, grader, improver):

1. Build the image: `bazel run //props/agents/<type>:load`
2. Tag for proxy: `podman tag localhost/props-<type>:latest 127.0.0.1:8000/<type>:latest`
3. Push to proxy: `podman push --tls-verify=false --creds="$ADMIN_AUTH" 127.0.0.1:8000/<type>:latest`

Alternatively, use curl to GET the manifest from the direct registry and PUT
it to the proxy:

```bash
curl -s -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  http://127.0.0.1:5050/v2/<type>/manifests/latest -o /tmp/manifest.json
curl -X PUT -u "$ADMIN_AUTH" \
  -H "Content-Type: application/vnd.docker.distribution.manifest.v2+json" \
  --data-binary @/tmp/manifest.json \
  http://127.0.0.1:8000/v2/<type>/manifests/latest
```

### Phase 4: Test Workflows

#### Critic

Run a critic on a snapshot via the API:

```bash
ADMIN_TOKEN=$(echo -n "$ADMIN_AUTH" | base64)
curl -X POST http://127.0.0.1:8000/api/runs/start \
  -H "Authorization: Basic $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "critic",
    "model": "gpt-5-mini",
    "example": {"type": "whole_snapshot", "snapshot_slug": "<slug>"}
  }'
```

**Verify:**

- Run appears in `agent_runs` with `status = 'in_progress'`
- After completion, `reported_issues` has findings for the run
- Issues have valid file paths and line ranges

#### Grader

Graders start automatically when the grader image is pushed. Verify:

```sql
SELECT agent_run_id, status, type_config->>'snapshot_slug' as snapshot
FROM agent_runs WHERE type_config->>'agent_type' = 'grader';
```

There should be one grader per snapshot, all `in_progress`.

#### Improver

Start an improver run and verify it proposes critic modifications:

```bash
curl -X POST http://127.0.0.1:8000/api/runs/start \
  -H "Authorization: Basic $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "improver",
    "model": "gpt-5-mini",
    "example": {"type": "whole_snapshot", "snapshot_slug": "<slug>"}
  }'
```

## Troubleshooting

### Graders not starting

The grader supervisor defers spawning until the HTTP backend is ready. If
graders don't appear:

1. Ensure the grader image was pushed to the **proxy** (port 8000)
2. Check backend logs for `Grader definition changed` / `Starting graders`
3. Restart the backend if needed

### Image resolution errors

Add insecure registry entries to
`~/.cache/claude-hooks/podman/registries.conf`:

```toml
[[registry]]
prefix = "127.0.0.1:5050"
location = "127.0.0.1:5050"
insecure = true

[[registry]]
prefix = "127.0.0.1:8000"
location = "127.0.0.1:8000"
insecure = true
```

### Password issues

Use hex-only passwords in `props/.devenv/state/pg_password` (no `/`, `+`, `=`
characters that break asyncpg DSN parsing).

## Configuration

`props/config.podman.toml` controls grader model and agent environment. Use
at least gpt-5 level models for meaningful results.

## Key Architecture Points

- **Registry proxy**: Integrated into the backend. Push images to port 8000
  (backend), which proxies to port 5050 (upstream registry) and records
  agent definitions.
- **Grader supervisor**: Listens for `grader_definition_changed` pg_notify.
  When a grader tag is pushed, all grader containers are (re)started.
- **Agent containers**: Run with host networking, per-agent PostgreSQL roles,
  and RLS-scoped database access.
