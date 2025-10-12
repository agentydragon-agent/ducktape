# Ember (v0)

This directory contains the minimal scaffolding for the containerised agent
pilot described in `ember/docs/pilot_plan.md`.

The pilot intentionally keeps the feature set extremely small:

- the agent loop runs inside a dedicated container (`agentd`)
- the only integration is Matrix chat (accessed directly using a scoped token)
- no policy gateway, approvals, or additional MCP tool surfaces
- health, restart, and shutdown are exposed via a tiny HTTP API
- OpenAI Responses API (`gpt-5`) is forced to call tools; encrypted reasoning
  traces are stored alongside tool calls in the on-disk history
- Reasoning replay follows the encrypted reasoning guidance in the OpenAI
  Responses API docs

The code here is **not** production ready. It gives the agent a sandbox that can
be iterated on while the surrounding control plane remains minimal.

## Kubernetes integration

The k3s deployment provisions Ember-specific credentials inside the `ember`
namespace:

- `matrix-ember-token` (Secret) – written by the matrix-stack Helm chart’s
  bootstrap job; contains the Matrix `access_token` for the `ember-bot` user.
- `gitea-ember-token` (Secret) – minted by the Gitea bootstrap job via the
  `gitea admin` CLI; includes `username`, `token`, and `token_name` fields.

Both jobs are idempotent; reapply the charts whenever you need to rotate the
credentials:

```bash
# Matrix credentials
helm upgrade matrix k8s/helm/matrix-stack -n matrix -f k8s/helm/matrix-stack/values.yaml

# Gitea credentials
kubectl apply -k k8s/gitea
```

The namespace definition lives at `k8s/ember/namespace.yaml` so GitOps can keep
it in sync with the rest of the stack.

## Running locally

The directory uses direnv + uv to manage an isolated virtual environment. Allow it once:

```bash
cd ember
direnv allow    # creates .venv and installs the package in editable mode
```

```bash
export MATRIX_BASE_URL="https://matrix.example.com"
export MATRIX_ACCESS_TOKEN="s3cret"
export MATRIX_ADMIN_USER_ID="@agentydragon:matrix.example.com"
export PILOT_STATE_DIR="${PWD}/.pilot-state"

export OPENAI_API_KEY="sk-..."

# optional: override the default model (gpt-5) if needed
# export OPENAI_MODEL="gpt-5.1"

# run the control API + runtime loop
agentd

# or use uvicorn directly:
# uvicorn ember.app:create_app --factory --reload
```

With that running you can:

- `curl http://127.0.0.1:8000/healthz`
- `curl -X POST http://127.0.0.1:8000/control/restart`
- `curl -X POST http://127.0.0.1:8000/control/shutdown`

The Matrix client polls the configured rooms and records unread messages. The
assistant is expected to use the `run_shell_command` tool to post replies (for
example via a CLI utility). No additional tool surfaces are exposed in this v0
pilot.

The runtime accepts invites from the `MATRIX_ADMIN_USER_ID` account. Accepted rooms
are persisted inside the pilot state directory so restarts automatically resume
listening in the same spaces.
