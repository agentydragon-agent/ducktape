---
name: web_selfcheck
description: >
  Diagnose the health of a Claude Code web session — checks whether
  web_setup.sh ran, whether the session start hook succeeded, whether
  the installed claude-hooks package is stale relative to the repo, and
  whether each SOPS-encrypted credential is decryptable and live-tests
  each one against its upstream API. Reports what's broken and how to fix
  it. Use when the user asks "did setup go ok", "why isn't bbr working",
  "check credentials", "selfcheck", or any question about web session health.
---

# Web Session Selfcheck

Comprehensive health check for a Claude Code web session. Run all checks,
then produce a single structured report with clear pass/fail status and
actionable remediation steps for anything that's broken.

Run all `Bash` commands with `dangerouslyDisableSandbox: true` (needs network
and filesystem access outside the sandbox).

## What to Check

Run all checks in parallel where possible.

---

### 1. web_setup.sh

**Goal**: confirm Nix and the `devtools` profile were installed successfully.

```bash
# Was it run at all?
ls -la /tmp/web-setup.log 2>/dev/null || echo "MISSING"
# Did it succeed? (last line should be "Setup complete.")
tail -5 /tmp/web-setup.log 2>/dev/null
# Was it recent? (mtime)
stat -c '%y' /tmp/web-setup.log 2>/dev/null
# Did Nix install?
nix --version 2>/dev/null || echo "nix not found"
# Is the devtools profile active?
nix profile list 2>/dev/null | grep -E 'devtools|claude-hooks' | head -5 || echo "no devtools profile"
```

**Failure indicators**: log missing, last line not "Setup complete", nix not
found, devtools not in profile list.

**Fix**: re-run setup from the Claude Code web UI setup command:

```
bash ducktape/devinfra/claude/web_setup.sh
```

---

### 2. Session Start Hook

**Goal**: confirm the session start hook ran successfully and wrote the env file.

```bash
# Find live session ID (from hook_daemon process)
LIVE=$(ps aux | grep hook_daemon | grep -v grep | grep -oP '(?<=--sock /tmp/claude-hd/)[^/]+' | head -1)
echo "live session: $LIVE"

# Check env file (presence + CANARY marker = success)
head -3 ~/.claude/session-env/$LIVE/sessionstart-hook-0.sh 2>/dev/null || echo "ENV FILE MISSING"

# Check daemon log for errors
grep -E 'ERROR|Exception|FileNotFoundError|sessionstart|SessionStart' \
  ~/.claude/session-env/$LIVE/hook-daemon/daemon.log 2>/dev/null | tail -20

# Is BUILDBUDDY_API_KEY set?
echo "BUILDBUDDY_API_KEY in env: $([ -n "${BUILDBUDDY_API_KEY:-}" ] && echo YES || echo NO)"

# Is the auth proxy running?
ls ~/.claude/session-env/$LIVE/auth-proxy/combined_ca.pem 2>/dev/null && echo "CA present" || echo "CA MISSING"
ls ~/.claude/session-env/$LIVE/bazelrc 2>/dev/null && echo "session bazelrc present" || echo "BAZELRC MISSING"

# Is the git proxy shim running? (bbr connects via 127.0.0.1:35233)
ss -tlnp 2>/dev/null | grep 35233 || echo "git proxy NOT listening on 35233"
```

**Common failure: `FileNotFoundError: Hook config not found: .claude_hooks/config.yaml`**

This means the installed `claude-hooks` package is stale — it still calls
`HookConfig.load_from_repo()` looking for `config.yaml`, but the repo was
refactored to use standalone `web.yaml`. See check #3.

**Fix if env file is missing**: re-trigger SessionStart on the live daemon:

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
source ~/.claude/session-env/$LIVE/sessionstart-hook-0.sh
```

**Manual fallback** (if daemon is down or still broken after fix):

```bash
source /home/user/ducktape/devinfra/secrets/web_env.sh
mkdir -p ~/.config/bazel
cat > ~/.config/bazel/buildbuddy.bazelrc <<EOF
common --remote_header=x-buildbuddy-api-key=${BUILDBUDDY_API_KEY}
build --config=rbe
EOF
```

---

### 3. claude-hooks Version Staleness

**Goal**: check whether the installed `claude-hooks` Nix package matches the
current repo code.

```bash
# Pinned commit (from npins/sources.json)
python3 -c "
import json
pins = json.load(open('/home/user/ducktape/npins/sources.json'))['pins']
url = pins.get('claude-hooks',{}).get('url','')
# Extract commit from release tag URL like: claude-hooks-095d71b
import re; m = re.search(r'claude-hooks-([0-9a-f]+)', url)
print('pinned commit:', m.group(1) if m else 'unknown', '  url:', url[:80])
"

# Current HEAD
git -C /home/user/ducktape rev-parse --short HEAD

# Key API change: does installed server.py still use HookConfig (old) or ProfileConfig (new)?
grep -c 'HookConfig' /nix/store/*claude-hooks-latest*/lib/python3.13/site-packages/devinfra/claude/hook_daemon/server.py 2>/dev/null \
  && echo "STALE: installed hooks uses HookConfig (old API, expects config.yaml)" \
  || echo "OK: installed hooks uses ProfileConfig (new API)"

# Commits on devinfra/claude/ since the pinned commit
# (pinned commit is often not in local history since it's the CI-released artifact)
# Instead, check when the npins entry was last updated:
git -C /home/user/ducktape log --oneline -5 -- npins/sources.json
```

**Failure indicator**: `grep -c 'HookConfig'` returns > 0 (old API detected).

**Root cause**: `npins/sources.json` pins `claude-hooks` to a specific GitHub
Release commit. The CI release workflow (`release.yml`) builds and publishes
the release; `sync-pins.yml` runs every 30 minutes to update the pin and push
to `devel`. If recent `devinfra/claude/` commits haven't been released yet,
or if the pin sync hasn't run, the installed package will be stale.

**Fix**:

1. Check if a release was published for the current code:
   - Look at GitHub Actions → `release.yml` runs on the `devel` branch
   - Check if `//:release_claude_hooks` completed after the relevant commit
2. If not released: trigger `release.yml` manually (workflow_dispatch) or
   push to `devel` to trigger CI
3. If released but pin not updated: `sync-pins.yml` runs every 30 min;
   check its last run or trigger manually (workflow_dispatch)
4. Once pin is updated and merged, re-run `web_setup.sh` in the session

---

### 4. Credentials — SOPS Decryption

**Goal**: confirm `SOPS_AGE_KEY` is present and can decrypt all claude-web secrets.

```bash
echo "SOPS_AGE_KEY present: $([ -n "${SOPS_AGE_KEY:-}" ] && echo YES || echo NO)"
echo "Age public key: $(echo "${SOPS_AGE_KEY:-}" | age-keygen -y 2>/dev/null || echo 'age-keygen not found')"

# Expected public key from .sops.yaml (claude-web entry):
grep 'claude-web' /home/user/ducktape/.sops.yaml

for f in \
  secrets/buildbuddy.yaml \
  secrets/github-pat-agentydragon-agent.yaml \
  secrets/github-ci-read-pat.yaml \
  secrets/alloy-otlp-bearer-token.yaml \
  secrets/claude-web-k8s-token.yaml \
  secrets/docker-ci/client-key.sops.pem; do
    result=$(sops -d /home/user/ducktape/$f 2>&1 | head -1)
    if echo "$result" | grep -qE 'FAILED|failed|error|Error'; then
        echo "FAIL: $f — $result"
    else
        echo "OK:   $f"
    fi
done
```

**Failure indicator**: any `FAIL` line, or `SOPS_AGE_KEY` not present.

**Fix**: if `SOPS_AGE_KEY` is missing, the session didn't receive the age
private key at startup. This is injected from the `claude-sandbox` k8s Secret
by the container runtime. Check whether the k8s Secret exists:

```bash
kubectl -n claude-sandbox get secret claude-web-age-key 2>/dev/null
```

---

### 5. Credentials — Live API Tests

Run each live test and capture HTTP status / response content.

#### BuildBuddy API Key

```bash
BB_KEY=$(sops -d /home/user/ducktape/secrets/buildbuddy.yaml 2>/dev/null \
  | awk '/buildbuddy_api_key:/ {print $2}')
# Test via bbapi (needs BUILDBUDDY_API_KEY in env)
export BUILDBUDDY_API_KEY="$BB_KEY"
curl -s -o /dev/null -w "%{http_code}" \
  -H "x-buildbuddy-api-key: $BB_KEY" \
  -H "Content-Type: application/proto" \
  "https://remote.buildbuddy.io/rpc/BuildBuddyService/GetUser" \
  --data-binary ''
```

Expected: `200` (or `400` for malformed proto — means auth passed).
`401`/`403` means key is invalid or expired.

**Fix if invalid**: regenerate key in BuildBuddy org settings, re-encrypt into
`secrets/buildbuddy.yaml`, push to `devel`, wait for `sync-pins.yml`.

#### GitHub Agent PAT (`agentydragon-agent`)

```bash
GH_TOKEN=$(sops -d /home/user/ducktape/secrets/github-pat-agentydragon-agent.yaml 2>/dev/null \
  | awk '/github_token:/ {print $2}')
curl -s -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/user \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('login:', d.get('login'), 'message:', d.get('message',''))"
```

Expected: `login: agentydragon-agent`.
`Bad credentials` or `Requires authentication` means token expired/revoked.

**Fix**: generate new PAT for `agentydragon-agent` machine user (Settings →
Developer Settings → Personal Access Tokens), re-encrypt into
`secrets/github-pat-agentydragon-agent.yaml`, push to `devel`.

#### GitHub CI Read PAT (`agentydragon` fine-grained)

```bash
GH_CI=$(sops -d /home/user/ducktape/secrets/github-ci-read-pat.yaml 2>/dev/null \
  | awk '/github_token:/ {print $2}')
curl -s -H "Authorization: Bearer $GH_CI" https://api.github.com/user \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('login:', d.get('login'), 'message:', d.get('message',''))"
```

Expected: `login: agentydragon`.

#### K8s Service Account Token

```bash
K8S_TOKEN=$(sops -d /home/user/ducktape/secrets/claude-web-k8s-token.yaml 2>/dev/null \
  | awk '/k8s_token:/ {print $2}')
curl -sk -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $K8S_TOKEN" \
  "https://api.allegedly.works:16443/api/v1/namespaces/claude-sandbox"
```

Expected: `200`. `401` means the token was rotated and the SOPS file wasn't
updated yet.

**Note**: this token is **auto-rotated by an in-cluster CronJob**. The SOPS
file should be updated automatically. If it returns 401, check:

```bash
# Check CronJob last run and next run
kubectl -n default get cronjob claude-web-token-rotator -o yaml 2>/dev/null | grep -E 'lastScheduleTime|schedule'
kubectl -n default get jobs -l app=claude-web-token-rotator 2>/dev/null | tail -5
```

#### OTLP Bearer Token (Grafana Alloy)

```bash
OTLP_TOKEN=$(sops -d /home/user/ducktape/secrets/alloy-otlp-bearer-token.yaml 2>/dev/null \
  | awk '/token:/ {print $2}')
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $OTLP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "https://alloy-otlp.allegedly.works/v1/traces"
```

Expected: `200` or `400` (bad proto = auth passed). `401` means token
was rotated. **Fix**: bump `rotation_version` in
`cluster/terraform/gitops/alloy-otlp-bearer-token/`, apply with `tofu`.

---

### 6. bbr / BuildBuddy RBE

```bash
# Set key from SOPS if not already in env
[ -z "${BUILDBUDDY_API_KEY:-}" ] && \
  export BUILDBUDDY_API_KEY=$(sops -d /home/user/ducktape/secrets/buildbuddy.yaml 2>/dev/null \
    | awk '/buildbuddy_api_key:/ {print $2}')

# Fix origin/HEAD if missing (needed by bbr)
git -C /home/user/ducktape remote set-head origin --auto 2>/dev/null || true

# Test bbr connectivity (dry run)
bbr build //devinfra:gazelle --nobuild 2>&1 | tail -5
```

**Failure: `cannot connect to 127.0.0.1:35233`** → session start hook didn't
run; the git proxy shim is not running. Follow session start hook fix above.

**Failure: `Unable to resolve host remote.buildbuddy.io`** → TLS proxy/CA
issue; session start hook didn't set up auth proxy. Follow session start hook
fix above.

---

## Report Format

After running all checks, produce:

```
# Web Session Selfcheck — <timestamp>

## Summary
<one-line: healthy / degraded / broken>

## Checks

| Check                        | Status | Detail                              |
|------------------------------|--------|-------------------------------------|
| web_setup.sh ran             | OK/FAIL| ...                                 |
| Session start hook           | OK/FAIL| CANARY present / FileNotFoundError  |
| claude-hooks version         | OK/STALE| pinned=<sha> head=<sha> diff=N commits |
| SOPS_AGE_KEY                 | OK/FAIL| age public key matches .sops.yaml   |
| Secret: buildbuddy.yaml      | OK/FAIL| decrypts / API <http_code>          |
| Secret: github-agent-pat     | OK/FAIL| decrypts / login=agentydragon-agent |
| Secret: github-ci-read-pat   | OK/FAIL| decrypts / login=agentydragon       |
| Secret: k8s-token            | OK/FAIL| decrypts / API <http_code>          |
| Secret: otlp-token           | OK/FAIL| decrypts / API <http_code>          |
| bbr / BuildBuddy RBE         | OK/FAIL| ...                                 |

## Issues & Remediation

### <issue title>
**Impact**: <what's broken>
**Root cause**: <why>
**Fix**: <exact commands or steps>

...
```

Prioritize issues by impact: hook failure > stale claude-hooks > credential
failures > CI pipeline issues.
