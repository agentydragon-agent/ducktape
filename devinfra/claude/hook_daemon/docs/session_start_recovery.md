# Session Start Hook Recovery (Claude Code Web)

When running in Claude Code Web (`CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE` is set), the
session start hook sets up Bazel, the auth proxy, TLS CA, SOPS secrets, BuildBuddy RBE,
and other tooling. Symptoms of failure: certificate errors, `bazelisk: command not found`,
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
- `SOPS_AGE_KEY` — always present in env; standard sops env var for age-based decryption

Without `BUILDBUDDY_API_KEY`, RBE is unavailable. All other secrets are non-critical.

## Step 1: Check if the env file was already written

A 500 response from the hook daemon often means the response _rendering_ failed, not the
setup itself — the daemon frequently writes the env file before the template error occurs.
Always check:

```bash
LIVE=$(ps aux | grep hook_daemon | grep -v grep | grep -oP '(?<=--sock /tmp/claude-hd/)[^/]+')
head -3 ~/.claude/session-env/$LIVE/sessionstart-hook-0.sh 2>/dev/null
# If it has the CANARY marker, source it:
source ~/.claude/session-env/$LIVE/sessionstart-hook-0.sh
bazelisk info  # verify it works
```

## Step 2: Re-trigger SessionStart on the live daemon

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

## Step 3: Manual assembly (daemon unavailable or env file missing)

If the daemon is down, manually assemble using SOPS (no k8s required):

**Decrypt secrets** — `SOPS_AGE_KEY` is always in env:

```bash
# Get the PYTHONPATH the daemon uses (needed for yaml, pyrage deps)
DAEMON_PY_PATH=$(cat /proc/$(pgrep -f hook_daemon | head -1)/environ 2>/dev/null \
  | tr '\0' '\n' | grep '^PYTHONPATH=' | cut -d= -f2-)

PYTHONPATH="$DAEMON_PY_PATH" python3.13 - <<'EOF'
from devinfra.claude.sops_decrypt import decrypt_sops_yaml
from pathlib import Path
# SOPS_AGE_KEY is inherited from the environment — sops reads it natively.
proj = Path("/home/user/ducktape")
bb = decrypt_sops_yaml(proj / "secrets/buildbuddy.yaml")
gh = decrypt_sops_yaml(proj / "secrets/github-pat-agentydragon-agent.yaml")
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
