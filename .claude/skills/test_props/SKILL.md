---
name: test_props
description: Run end-to-end props testing with a real OpenAI API key. Tests critic, grader, improver, and optimizer workflows in a podman + host networking environment.
argument-hint: "[workflow: setup|critic|grader|improver|all]"
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, WebFetch, Task
---

# Test Props E2E

Run end-to-end props testing. Sets up infrastructure, initializes the database,
runs the backend, pushes agent images, and tests agent workflows.

**Argument:** `$ARGUMENTS` (default: `all`)

- `setup` - Only set up infrastructure, database, backend, and push images
- `critic` - Run a critic on a snapshot and verify output
- `grader` - Verify graders are running and grading
- `improver` - Test improver agent
- `all` - Full setup + test all workflows

## Prerequisites

- `OPENAI_API_KEY` must be in environment
- Podman must be running (claude_hooks handles this)

## Phase 0: Specimens Repo

Clone the specimens repo if not present:

```bash
if [ ! -d /home/user/specimens ]; then
  git clone https://github.com/agentydragon/specimens /home/user/specimens
fi
```

If authentication is needed, use the GitHub token:

```bash
git clone https://${DUCKTAPE_CI_READ_GITHUB_TOKEN}@github.com/agentydragon/specimens /home/user/specimens
```

## Phase 1: Infrastructure Setup

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

## Phase 2: Start Backend

1. Check if backend is already running:

   ```bash
   curl -s http://127.0.0.1:8000/health
   ```

   If not running, start it in the background with these env vars:

   ```bash
   export PROPS_CONFIG_FILE=props/config.podman.toml
   export PROPS_REGISTRY_HOST=127.0.0.1
   export PROPS_REGISTRY_PORT=8000
   export PROPS_REGISTRY_UPSTREAM_URL=http://127.0.0.1:5050
   export PROPS_DOCKER_NETWORK=host
   bazel run //props/backend:backend_cli -- serve --host 127.0.0.1 --port 8000
   ```

## Phase 3: Push Agent Images

Push images to the **registry proxy** (port 8000), not the direct registry
(port 5050). The proxy records agent definitions and the grader supervisor
listens for grader tag changes.

```bash
ADMIN_AUTH="postgres:$(cat props/.devenv/state/pg_password)"
```

For each agent type needed (critic, grader, improver):

1. Build: `bazel run //props/agents/<type>:load`
2. Tag: `podman tag localhost/props-<type>:latest 127.0.0.1:8000/<type>:latest`
3. Push: `podman push --tls-verify=false --creds="$ADMIN_AUTH" 127.0.0.1:8000/<type>:latest`

Alternatively, copy the manifest from the direct registry to the proxy:

```bash
curl -s -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  http://127.0.0.1:5050/v2/<type>/manifests/latest -o /tmp/manifest.json
curl -X PUT -u "$ADMIN_AUTH" \
  -H "Content-Type: application/vnd.docker.distribution.manifest.v2+json" \
  --data-binary @/tmp/manifest.json \
  http://127.0.0.1:8000/v2/<type>/manifests/latest
```

## Phase 4: Test Workflows

### Critic

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

**Verify critic completion:**

1. Poll until the critic run completes:

   ```sql
   SELECT agent_run_id, status FROM agent_runs
   WHERE agent_run_id = '<run_id>';
   ```

   Wait until `status = 'completed'`.

2. Check that `reported_issues` has findings:

   ```sql
   SELECT COUNT(*) FROM reported_issues
   WHERE agent_run_id = '<run_id>';
   ```

   There should be at least one reported issue.

3. Issues should have valid file paths and line ranges:

   ```sql
   SELECT ri.issue_id, ri.title, rio.locations
   FROM reported_issues ri
   JOIN reported_issue_occurrences rio
     ON rio.agent_run_id = ri.agent_run_id AND rio.reported_issue_id = ri.issue_id
   WHERE ri.agent_run_id = '<run_id>';
   ```

### Grader

Graders start automatically when the grader image is pushed. Verify:

```sql
SELECT agent_run_id, status, type_config->>'snapshot_slug' as snapshot
FROM agent_runs WHERE type_config->>'agent_type' = 'grader';
```

There should be one grader per snapshot, all `in_progress`.

**Verify grading after critic:**

Once the critic run completes and graders are running, verify that grading
happens — the grader should create `grading_edges` for the critic's issues.

1. Check `grading_pending` for drift (missing grading edges):

   ```sql
   SELECT COUNT(*) FROM grading_pending
   WHERE critique_run_id = '<critic_run_id>';
   ```

2. Poll until the count reaches 0. This means all grading edges have been
   created — every reported issue has been compared against every relevant
   ground truth occurrence.

3. Verify `grading_edges` exist:

   ```sql
   SELECT ge.critique_run_id, ge.critique_issue_id,
          ge.tp_id, ge.fp_id, ge.grade
   FROM grading_edges ge
   WHERE ge.critique_run_id = '<critic_run_id>';
   ```

   There should be at least one grading edge per reported issue.

### Improver

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

## Key Architecture Points

- **Registry proxy**: Integrated into the backend. Push images to port 8000
  (backend), which proxies to port 5050 (upstream registry) and records
  agent definitions.
- **Grader supervisor**: Listens for `grader_definition_changed` pg_notify.
  When a grader tag is pushed, all grader containers are (re)started.
- **Agent containers**: Run with host networking, per-agent PostgreSQL roles,
  and RLS-scoped database access.
- **Model selection**: Use at least gpt-5 level models for meaningful results.
  Config file: `props/config.podman.toml`.
