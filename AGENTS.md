@README.md

## Target Platform

Linux by default. macOS-only components (Seatbelt, Sandboxer) are explicitly documented.

@STYLE.md

## Recovering from a Broken Session Start Hook (Claude Code Web)

When running in Claude Code Web (`CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE` is set), the
session start hook sets up Bazel, the auth proxy, TLS CA, SOPS secrets, BuildBuddy RBE,
and other tooling. Symptoms of failure: certificate errors, `bazel: command not found`,
`Unable to resolve host remote.buildbuddy.io`, missing env files.

**Check the daemon log first:**

```bash
LIVE=$(ps aux | grep hook_daemon | grep -v grep | grep -oP '(?<=--sock /tmp/claude-hd/)[^/]+')
tail -100 ~/.claude/session-env/$LIVE/hook-daemon/daemon.log
```

**Recovery: read the implementation to understand what failed.**

1. Read <devinfra/claude/hook_daemon/session_start/handler.py> for the full setup sequence
2. Read <devinfra/claude/README.md> for architecture context
3. Read `.claude_hooks/config.yaml` for secrets config (SOPS files and k8s settings)
4. Read <devinfra/claude/config/bazelrc.mako> for the session bazelrc template

**Key facts about secrets (changed from k8s to SOPS):**

- `BUILDBUDDY_API_KEY` — decrypted from `secrets/buildbuddy.yaml` (SOPS, age key in env)
- `GITHUB_TOKEN` — decrypted from `secrets/github-pat-agentydragon-agent.yaml` (SOPS)
- `k8s_token` — decrypted from `secrets/claude-web-k8s-token.yaml` (SOPS); also available
  as `DUCKTAPE_CLAUDE_HOOKS_K8S_TOKEN` env var (injected by the cluster at container start)
- `otel_bearer_token` — fetched from k8s secret (non-critical, only for tracing)
- `DUCKTAPE_CLAUDE_HOOKS_AGE_KEY` — always present in env; used to decrypt all SOPS files

Without `BUILDBUDDY_API_KEY`, RBE is unavailable. All other secrets are non-critical.

### Step 1: Check if the env file was already written

A 500 response from the hook daemon often means the response _rendering_ failed, not the
setup itself — the daemon frequently writes the env file before the template error occurs.
Always check:

```bash
LIVE=$(ps aux | grep hook_daemon | grep -v grep | grep -oP '(?<=--sock /tmp/claude-hd/)[^/]+')
head -3 ~/.claude/session-env/$LIVE/sessionstart-hook-0.sh 2>/dev/null
# If it has the CANARY marker, source it:
source ~/.claude/session-env/$LIVE/sessionstart-hook-0.sh
bazel info  # verify it works
```

### Step 2: Re-trigger SessionStart on the live daemon

If the env file is missing or incomplete, re-trigger the hook:

```bash
LIVE=<live_session_id>
SOCK=/tmp/claude-hd/$LIVE/d.sock
python3.13 -c "
import json, os
env = dict(os.environ)
env['CLAUDE_ENV_FILE'] = f'/root/.claude/session-env/$LIVE/sessionstart-hook-0.sh'
env['CLAUDE_PROJECT_DIR'] = '/home/user/ducktape'
env['CLAUDE_CODE_REMOTE'] = 'true'
print(json.dumps({'hook': {'hook_event_name': 'SessionStart', 'session_id': '$LIVE',
  'cwd': '/home/user/ducktape', 'transcript_path': '/tmp/transcript.json',
  'source': 'startup'}, 'env': env}))
" | curl -s --max-time 300 --unix-socket $SOCK http://localhost/hook -X POST \
  -H 'Content-Type: application/json' -d @-
# Then source regardless of HTTP status (500 may still mean env file was written):
source ~/.claude/session-env/$LIVE/sessionstart-hook-0.sh
```

### Step 3: Manual assembly (daemon unavailable or env file missing)

If the daemon is down, manually assemble using SOPS (no k8s required):

**Decrypt secrets** — `DUCKTAPE_CLAUDE_HOOKS_AGE_KEY` is always in env:

```bash
# Get the PYTHONPATH the daemon uses (needed for yaml, pyrage deps)
DAEMON_PY_PATH=$(cat /proc/$(pgrep -f hook_daemon | head -1)/environ 2>/dev/null \
  | tr '\0' '\n' | grep '^PYTHONPATH=' | cut -d= -f2-)

PYTHONPATH="$DAEMON_PY_PATH" python3.13 - <<'EOF'
import os
from devinfra.claude.sops_decrypt import load_age_identities, decrypt_sops_yaml
from pathlib import Path
ids = load_age_identities(os.environ["DUCKTAPE_CLAUDE_HOOKS_AGE_KEY"])
proj = Path("/home/user/ducktape")
bb = decrypt_sops_yaml(proj / "secrets/buildbuddy.yaml", ids)
gh = decrypt_sops_yaml(proj / "secrets/github-pat-agentydragon-agent.yaml", ids)
print(f"export BUILDBUDDY_API_KEY={bb['buildbuddy_api_key']}")
print(f"export GITHUB_TOKEN={gh['github_token']}")
EOF
```

**Configure BuildBuddy** (writes `~/.config/bazel/buildbuddy.bazelrc`):

```bash
BUILDBUDDY_API_KEY=<from above>
mkdir -p ~/.config/bazel
cat > ~/.config/bazel/buildbuddy.bazelrc <<EOF
common --remote_header=x-buildbuddy-api-key=${BUILDBUDDY_API_KEY}
build --config=rbe
EOF
```

**Assemble the minimal env file** — copy from a previous session and patch the session ID:

```bash
PREV=$(ls ~/.claude/session-env/ | grep -v "$LIVE" | head -1)
SD=~/.claude/session-env/$LIVE
mkdir -p "$SD"
sed "s|$PREV|$LIVE|g" ~/.claude/session-env/$PREV/sessionstart-hook-0.sh > "$SD/sessionstart-hook-0.sh"
source "$SD/sessionstart-hook-0.sh"
```

If no previous session exists, write from scratch (fill in `<LIVE>` with the session ID):

```bash
SD=~/.claude/session-env/<LIVE>
mkdir -p "$SD/auth-proxy" "$SD/bin"
cat > "$SD/sessionstart-hook-0.sh" <<'ENVEOF'
export PATH="<SD>/bin:$PATH"
export SESSION_BAZELRC="<SD>/bazelrc"
export BAZELISK_PATH="/usr/local/bin/bazelisk"
export DUCKTAPE_CLAUDE_HOOKS_SESSION_DIR="<SD>"
export DUCKTAPE_CLAUDE_HOOKS_SUPERVISOR_PORT="19001"
export SSL_CERT_FILE="<SD>/auth-proxy/combined_ca.pem"
export REQUESTS_CA_BUNDLE="<SD>/auth-proxy/combined_ca.pem"
export CURL_CA_BUNDLE="<SD>/auth-proxy/combined_ca.pem"
export NODE_EXTRA_CA_CERTS="<SD>/auth-proxy/combined_ca.pem"
export DOCKER_HOST="unix:///var/run/docker.sock"
export GITHUB_TOKEN="<from SOPS above>"
export BUILDBUDDY_API_KEY="<from SOPS above>"
export DUCKTAPE_PRECOMMIT_ENFORCE_BAZEL_TESTS="0"
export NO_PROXY="localhost,127.0.0.1,169.254.169.254,metadata.google.internal,*.svc.cluster.local,*.local"
export no_proxy="$NO_PROXY"
ENVEOF
```

Note: without the auth proxy CA (`combined_ca.pem` and `cacerts.jks`), Bazel repository
rules and the JVM truststore won't work. The CA files are created by the daemon. If the
daemon is completely unavailable, re-run `devinfra/claude/web_setup.sh` to reinstall it.

**Verify**:

```bash
bazel info           # should show output_base in session-env
bazel test //devinfra/claude:test_sops_decrypt  # passes via RBE
```

**Do NOT** bypass certificate/proxy errors with `--noverify`, `SSL_VERIFY=false`, etc. The root cause is always a missing/broken session start hook. Notify the user.

## Sandbox

Run `bazel`, `terraform`/`tofu`, `kubectl`, `systemctl`, `ss`, `ip`, `curl`, and other network/system commands **outside the sandbox** (`dangerouslyDisableSandbox: true`). The sandbox blocks their network calls (including localhost, e.g., `kubectl` to haproxy on `localhost:7445`).

## Refactoring

When renaming/moving/deleting files or symbols, search **all references** across the entire codebase (imports, BUILD files, CI configs, docs, Dockerfiles, k8s manifests). Missing a reference is worse than being thorough.

**Atomic API changes**: update all callers in the same commit. No transitional shims within this monorepo.

## Before Hand-off

```bash
bazel build //...
bazel test //...
```

Lint (ruff + mypy) runs by default. Use `--config=nolint` to skip.
If you touched `ansible/`, also follow <ansible/AGENTS.md>.

## Git

**NEVER amend a commit that has already been pushed.**

**NEVER use `git reset --soft` to squash onto a base branch that has moved on the remote.** `git reset --soft origin/devel` collapses _all_ differences between HEAD and `origin/devel` into the staging area — including commits other people landed on devel since your branch diverged. The resulting "squashed" commit silently re-applies every upstream change as if it were yours. Use `git rebase origin/devel` first to rebase, then squash with `git reset --soft $(git merge-base HEAD origin/devel)` so only your branch's changes are staged.

## Debug Notes

Convention: `<subproject>/debug/<topic>.md` for persistent investigation notes (RCAs, debug logs). Examples: `debug/spice_lag/README.md`, `debug/wyrm-oom/INVESTIGATION.md`. The `cluster/` subproject uses `cluster/docs/lessons_learned/` instead.

## Plans

`plans/` directories are for future work or work in progress. Once a plan is fully completed, remove it from `plans/` (delete, or squash into a short tombstone/summary elsewhere).

## TODO Tracking

Subprojects use `TODO.md` for persistent TODO tracking. TODOs local to a specific code location are fine as inline comments; cross-cutting or project-level TODOs belong in `TODO.md`.

## Testing

**Always use Bazel**, not direct pytest/python:

```bash
bazel test //path/to:test_target
bazel run //path/to:binary_target
```

**CRITICAL gotcha**: All `py_test` targets MUST have a `pytest_bazel.main()` entry point. Without it, Bazel runs the file as a script which exits 0 without running tests. Add `@pypi//pytest_bazel` to deps.

```python
import pytest_bazel
# ... tests ...
if __name__ == "__main__":
    pytest_bazel.main()
```

**pytest-asyncio auto mode**: configured via `conftest.py` hooks. Do NOT add `@pytest.mark.asyncio` decorators.

**No test skips for missing tools**: let the test fail. Tools come from Bazel runfiles or the RBE worker image.

**Docker tests run on RBE, never locally**: Tests that use Docker (e.g., container E2E tests, proxy integration tests with mitmproxy testcontainers) are designed to run on BuildBuddy RBE workers, which have Docker available. **Never** skip these tests because Docker is unavailable locally, disable them, or claim they are "not runnable." They work on RBE — that is the intended execution environment. If RBE is not working, recover it by following the "Recovering from a Broken Session Start Hook" section above. Every environment in which agents operate will have BuildBuddy accessible, either automatically (session start hook) or through manual recovery. If you cannot restore BuildBuddy remote execution after following recovery steps, **abort and report the issue to the user** rather than working around it with `--remote_executor=""` or local-only execution for tests that assume RBE.

Use the `py_test` macro from `//devinfra/testing:defs.bzl` (not the raw `@rules_python` `py_test`) and set `requires_docker = True`. The macro handles `env_inherit`, tags, and Docker exec properties automatically. Do not add `env_inherit = ["DOCKER_HOST"]` or `tags = ["requires_docker"]` manually.

**Use undeclared test outputs for log capture**: Write diagnostic data (container logs, HAR dumps, config snapshots) to Bazel's undeclared test outputs directory via `util.testing.undeclared_outputs.undeclared_outputs_dir()`. These are uploaded to BuildBuddy and retrievable from the invocation. Do not dump large log blobs into test stdout/stderr — they clutter the test log and are harder to navigate. To read undeclared outputs from a test run:

```bash
TEST_DIR=$(bazel info bazel-testlogs)/path/to/test_target
ls "$TEST_DIR/test.outputs/"          # list undeclared output files
cat "$TEST_DIR/test.outputs/my.log"   # read a specific output
```

On RBE, the outputs are downloaded to the local testlogs dir after the test completes (Bazel fetches them automatically). The mitmproxy fixture saves `proxy.har` to undeclared outputs as an example; see `test_k8s_proxy_integration.py` for container log capture.

**Test timeouts mean hangs, not slowness**: When a test times out, assume it is wedged — an internal operation is waiting on something that will never arrive (deadlock, stuck future, container that never becomes ready, connection to a port nothing is listening on). Do NOT bump `size`/`timeout` as a fix. Instead, trace the execution to find what is blocked: run with `--test_output=streamed --test_arg=-s`, add logging around fixture setup, check for stuck containers (`docker ps`), etc. A test that ran in 35s last week and now times out at 60s is not "slow" — something broke internally.

### Updating syrupy snapshots

Snapshot tests use syrupy (`.ambr` files in `__snapshots__/`). The `.ambr` files must
be listed in the test target's `data` glob (e.g., `glob(["__snapshots__/*.ambr"])`).

To update after intentional changes, run the test on RBE with `--snapshot-update`, then
copy the updated `.ambr` file from the runfiles tree back to the source tree:

```bash
# 1. Run on RBE with snapshot-update (writes into runfiles, not source tree)
bazel test //path/to:snapshot_test \
  --test_arg=--snapshot-update \
  --nocache_test_results

# 2. Copy updated snapshots back to source tree
cp bazel-bin/path/to/snapshot_test.runfiles/_main/path/to/__snapshots__/snapshot_test.ambr \
   path/to/__snapshots__/snapshot_test.ambr
```

**Why not `--remote_executor=""`?** On NixOS, `/bin/bash` doesn't exist, which breaks
the Ruff lint aspect when running locally. Running on RBE avoids this.

Then commit the updated `.ambr` files.

### Live OpenAI API Tests

Use `live_openai_py_test` from `//openai_utils/testing:testing.bzl`. Generates `.mock` and `.live` targets. CI excludes `.live` via `--test_tag_filters=-live_openai_api`.

```python
# test_foo.py
async def test_mock(mock_client): ...

@pytest.mark.live_openai_api
async def test_live(live_openai): ...
```

## JavaScript / TypeScript

Uses `@aspect_rules_js`. **Do NOT run raw `pnpm install`** -- Bazel manages pnpm (pinned in `MODULE.bazel`).

Adding deps: add to `package.json`, run Bazel (first build updates lockfile and fails), run again, commit `pnpm-lock.yaml`.

See <props/frontend/AGENTS.md> for frontend conventions.
