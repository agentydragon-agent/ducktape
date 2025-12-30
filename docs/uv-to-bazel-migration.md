# Bazel Migration Status

## Target State

Unified Bazel build system for all Python packages:
- Single `bazel build //...` and `bazel test //...` commands
- `rules_python` for Python 3.12+
- Session start hooks set up Bazel proxy for Claude Code web

## Current Status

**Completed:**
- MODULE.bazel with rules_python configured
- All Python packages have BUILD.bazel files
- pip.parse with requirements_bazel.txt from uv export
- Circular dependency resolved (bootstrap_handler moved to mcp_infra)
- Session start hooks for Claude Code web Bazel proxy

**In Progress:**
- Node.js frontends remain on pnpm (not yet migrated to rules_js)
- Docker images built with Dockerfiles (not rules_oci)
- Website uses Hakyll/stack (very slow Haskell builds)

## Package Structure

All Python packages use `src/` layout:
```
package_name/
├── BUILD.bazel
├── pyproject.toml      # pytest config only
├── src/package_name/
│   ├── __init__.py
│   └── ...
└── tests/
```

## Session Hooks

Claude Code web sessions use a session start hook to configure Bazel:

1. **Hook config:** `.claude/settings.json` runs `python3 -m claude_web_hooks.session_start`
2. **Package:** `claude_web_hooks/` contains:
   - `proxy.py` - Local auth proxy for TLS-inspecting proxy
   - `bazel_proxy_setup.py` - Setup logic (CA extraction, truststore, bazelrc)
   - `session_start.py` - Main hook entry point

The hook handles:
- Starting local proxy at `localhost:18081` for BCR access
- Creating Java truststore with TLS inspection CA
- Writing `~/.bazelrc` with proxy configuration

## Remaining Work

### High Priority

1. **Enable remote cache write in CI**
   - Currently read-only (`--remote_upload_local_results=false`)
   - Enable for main branch for better cache hit rates

2. **Lint/type check via Bazel**
   - Add `aspect_rules_lint` for ruff/mypy as test targets
   - Replace pre-commit ruff/mypy with Bazel-native checks

### Medium Priority

3. **Node.js frontends (rules_js)**
   - `props/frontend`, `rspcache/admin_ui`, `agent_server/web`
   - Currently use pnpm outside Bazel

4. **Docker images (rules_oci)**
   - Start with critical images, evaluate complexity vs Dockerfiles

### Low Priority / Evaluate

5. **Website**
   - Haskell builds extremely slow from scratch
   - Consider keeping `stack build` outside Bazel

6. **Agent tar builds (`agent_pkg_tar` rule)**
   - Custom rule for agent definition archives
   - Dockerfile + build context as tar

## Commands Reference

```bash
bazel build //...           # Build everything
bazel test //...            # Test everything
bazel build //adgn:adgn     # Build specific package
bazel test //adgn:tests     # Test specific package
```

## Known Issues

### rules_python lock() doesn't inherit --action_env

The `lock()` rule sets explicit `env` on `ctx.actions.run_shell()`, bypassing `--action_env`.

**Workaround:** Pass proxy env vars directly to `lock()` rule's `env` attribute.
