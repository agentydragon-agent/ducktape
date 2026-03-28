# Claude Code session start hook — ${status}

% if proxy:
**Environment:** gVisor sandbox, TLS-inspecting proxy, no overlay fs (vfs), 9p fs
**Bazel:** wrapper adds auth proxy (port ${proxy.port}, ${proxy.ca_status})
% else:
**Environment:** CLI (local)
% endif
% if container:

## Docker
${container.status}, `DOCKER_HOST=${container.socket_url}`
- `docker run` works. `docker build --network=host` works (BuildKit handles large output gracefully).
  Details: <devinfra/claude/docs/docker_evaluation_results.md>
  Use `--network=host` for builds; Alpine apk may need `--no-check-certificate` for TLS proxy.
- Storage: \
% if container.storage_driver == "overlay":
overlay on tmpfs (layer caching works for <~35 layers). Use `--layers=false` for larger Dockerfiles.
% else:
VFS on 9p (no layer caching, slower builds).
% endif
% endif
% if mkcert:

## Localhost TLS
`$MKCERT_CERT` / `$MKCERT_KEY` (auto-trusted). Use for HTTPS dev servers.
% endif
% if isinstance(precommit, PrecommitInstallingHooks):

## pre-commit
Hook environments installing in background. First `git commit` may block briefly.
% elif isinstance(precommit, PrecommitNotInstalled) or precommit is None:

## pre-commit
**Warning**: pre-commit hook installation failed. Git hooks may not run. Check daemon log for details.
% endif
% if secrets:

## Secrets
${len(secrets.env_vars)} env var(s) loaded from k8s cluster secrets.
% if secrets.kubeconfig_path:
`kubectl` access available: `cluster/k8s/{claude,agent-shared}-rbac/` includes admin in `claude-sandbox` namespace, read-only in `props`.
% endif
% else:

## Secrets — UNAVAILABLE
K8s secrets could not be fetched. This means:
- `GITHUB_TOKEN` is not set — `gh` CLI and authenticated git operations will fail
- `BUILDBUDDY_API_KEY` is not set — Bazel remote cache/execution (RBE) is unavailable
- `KUBECONFIG` is not set — `kubectl` will not work

**Recovery steps:**
1. Check the daemon log for the root cause: `tail -50 ${log_file}`
2. Common cause: proxy tunnel returned 403 (k8s token expired or proxy auth failed)
3. Look for a previous working session's env file under `~/.claude/session-env/*/sessionstart-hook-0.sh` and copy `GITHUB_TOKEN` and `BUILDBUDDY_API_KEY` values
4. Export them manually: `export GITHUB_TOKEN=... BUILDBUDDY_API_KEY=...`

**Notify the user** that secrets are unavailable and Bazel RBE / GitHub operations will not work until resolved.
% endif
% if buildbuddy_configured:

## BuildBuddy
Bazel builds and tests by default execute remotely via BuildBuddy.
Use BuildBuddy API (key in `~/.config/bazel/buildbuddy.bazelrc`) to download undeclared test outputs, profiles, search invocations.
% endif

% if any(r.levelno >= WARNING for r in log_entries):

## Warnings
% for record in log_entries:
% if record.levelno >= WARNING:
<%
    msg = record.getMessage()
    display_msg = msg[:200] + " [truncated — see log]" if len(msg) > 200 else msg
%>\
- ${record.levelname}: ${display_msg}
% endif
% endfor
% endif

Session start log: `${log_file}`
% if extra_context:
${extra_context}
% endif
