# Bazel Migration Status

## Target State

Unified Bazel build system for all Python packages:
- Single `bazel build //...` and `bazel test //...` commands
- `rules_python` for Python 3.12+
- Session start hooks set up Bazel proxy for Claude Code web

## Current Status (January 2026)

### Coverage Summary

| Metric | Count | Notes |
|--------|-------|-------|
| Python files total | 1133 | Git-tracked only |
| In Bazel py_* srcs | 1064 | 95.2% coverage |
| Not in any target | 54 | See list below |
| Intentionally excluded | 15 | ansible (12), nix (3) |
| py_library targets | 44 | |
| py_test targets | 29 | 3 manual |
| ruff_test targets | 39 | Linting coverage |

Run `./bazelization/audit.py` to get updated counts.

### Completed

- MODULE.bazel with rules_python configured
- Most Python packages have BUILD.bazel files
- pip.parse with requirements_bazel.txt from uv export
- Circular dependency resolved (bootstrap_handler moved to mcp_infra)
- Session start hooks for Claude Code web Bazel proxy
- `aspect_rules_lint` integrated for ruff linting (`bazel lint //...`)

### In Progress / Partial

- Node.js frontends remain on pnpm (not yet migrated to rules_js)
- Docker images built with Dockerfiles (not rules_oci)
- Website uses Hakyll/stack (very slow Haskell builds)

### Intentionally Not Bazelized

| Directory | Reason |
|-----------|--------|
| `ansible/` | Ansible modules managed by Ansible Galaxy |
| `nix/` | Nix configuration files, not Python packages |
| `finance/gnucash_util.py` | Requires system gnucash library |

### Manual Targets (require special environment)

| Target | Reason |
|--------|--------|
| `//claude/claude_optimizer:test_integration` | Requires docker/external resources |
| `//experimental/cotrl:test_llm_rl_minimal` | Requires OPENAI_API_KEY |
| `//gnome-terminal-profile-switcher:*` | Requires DBUS/GNOME session |
| `//homeassistant/iaqi:requirements*` | Separate requirements lock |
| `//mcp_starter:test_integration` | Requires running MCP server |
| `//website:*` | Haskell/stack build system |

### Files Not in Any Bazel Target (54 files)

| Directory | Count | Notes |
|-----------|-------|-------|
| `inventree_utils/` | 23 | Entire package not Bazelized |
| `llm/` (examples/scripts) | 6 | Example and manual test scripts |
| `experimental/ember_evals/` | 5 | Missing submodules, incomplete |
| `k8s/helm/*/files/` | 4 | Helm chart Python scripts |
| `adgn/` (examples, gitea_pr_gate) | 4 | Subpackages not in srcs |
| `trilium/` | 3 | Papers/search scripts |
| `sandboxed_jupyter/examples/` | 2 | Example scripts |
| Other standalone files | 7 | Root conftest, dotfiles, gatelet/tasks, etc. |

## Package Structure

Most Python packages use `src/` layout:
```
package_name/
├── BUILD.bazel
├── pyproject.toml      # pytest config only
├── src/package_name/
│   ├── __init__.py
│   └── ...
└── tests/
```

Experimental packages use flat layout:
```
experimental/package_name/
├── BUILD.bazel
├── package_name.py
└── test_package_name.py
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

## Action Items

### High Priority

1. **Enable remote cache write in CI**
   - Currently read-only (`--remote_upload_local_results=false`)
   - Enable for main branch for better cache hit rates

2. **Fix ember_evals missing modules**
   - Add missing .kubernetes, .matrix, .steps, .models submodules
   - Or remove if abandoned

### Medium Priority

3. **Node.js frontends (rules_js)**
   - `props/frontend`, `rspcache/admin_ui`, `agent_server/web`
   - Currently use pnpm outside Bazel

4. **Docker images (rules_oci)**
   - Start with critical images, evaluate complexity vs Dockerfiles

5. **Add mypy integration**
   - Extend aspect_rules_lint for mypy type checking
   - Currently only ruff is integrated

### Low Priority / Evaluate

6. **Website**
   - Haskell builds extremely slow from scratch
   - Consider keeping `stack build` outside Bazel

7. **Rust crates (rules_rust)**
   - `finance/worthy/` uses Cargo

## Future Structure Goals

### Tests Colocated with Production Code

Current: tests in separate `tests/` directory
Target: tests alongside the code they test

```
# Current (src/tests split)
package_name/
├── src/package_name/
│   ├── module.py
│   └── ...
└── tests/
    └── test_module.py

# Target (colocated)
package_name/
├── src/package_name/
│   ├── module.py
│   └── module_test.py  # or test_module.py
```

Benefits:
- Tests visible next to code they test
- Easier to see coverage gaps
- Simpler BUILD files (single glob)

## Non-Bazel Infrastructure Inventory

### pyproject.toml Files (39 packages)

Each package has a pyproject.toml with varying content:

| Content Type | Purpose | Target State |
|--------------|---------|--------------|
| `[tool.pytest]` | pytest configuration | Keep (not Bazel-managed) |
| `[tool.mypy]` | mypy configuration | Keep (used by pre-commit) |
| `[tool.ruff]` | ruff overrides | Migrate to root ruff.toml |
| `[project]` deps | Package dependencies | Remove (use requirements_bazel.txt) |
| `[tool.uv.workspace]` | uv workspace | Keep until fully on Bazel |

Root `pyproject.toml` contains:
- `[tool.uv]` override-dependencies and sources
- `[tool.ruff]` (duplicate of ruff.toml - should consolidate)
- `[tool.uv.workspace]` members list

### Linting Configuration

| Tool | Config Location | Bazel Integration |
|------|-----------------|-------------------|
| Ruff | `ruff.toml` (root) | `bazel lint //...` via aspect_rules_lint |
| mypy | Per-package `pyproject.toml` or `mypy.ini` | Not yet (pre-commit only) |
| buildifier | Pre-commit hook | Pre-commit only |
| yamllint | `.yamllint.yaml` | Pre-commit only |
| alejandra | Pre-commit hook (nix) | Pre-commit only |
| ESLint | `adgn/src/adgn/agent/web/`, `props/frontend/` | Pre-commit only |
| Prettier | Same as ESLint | Pre-commit only |

### Pre-commit Hooks (`.pre-commit-config.yaml`)

| Hook | Purpose | Bazel Equivalent |
|------|---------|------------------|
| `no-commit-to-branch` | Block commits to main | N/A (git hook) |
| `check-ast` | Valid Python syntax | `bazel build` catches |
| `check-yaml` | Valid YAML | N/A |
| `check-toml` | Valid TOML | N/A |
| `yamllint` | YAML style | N/A |
| `ansible-syntax-check` | Ansible validation | N/A |
| `ruff-check` | Linting | `bazel lint //...` |
| `ruff-format` | Formatting | `bazel lint //...` |
| `mypy` (12 configs) | Type checking | TODO: aspect_rules_lint |
| `buildifier` | BUILD formatting | TODO: aspect_rules_lint |
| `alejandra` | Nix formatting | N/A |
| `eslint` | JS/TS linting | TODO: rules_js |
| `prettier` | JS/TS formatting | TODO: rules_js |
| `svelte-check` | Svelte types | TODO: rules_js |

### Other Configuration Files

| File | Purpose | Notes |
|------|---------|-------|
| `.yamllint.yaml` | yamllint config | Pre-commit only |
| `mypy.ini` | Root mypy config | Used by adgn, critic_util |
| `mypy-homeassistant.ini` | HA-specific mypy | Used by homeassistant/iaqi |
| `Cargo.toml` | Rust workspace | finance/worthy uses Cargo |
| `.bazelrc` | Bazel config | Generated by session hook |
| `.bazelignore` | Bazel ignore patterns | Static |

### Known Duplication

1. **Ruff config**: `ruff.toml` and `pyproject.toml [tool.ruff]` both exist
2. **First-party packages**: Listed in both `ruff.toml` and `pyproject.toml`
3. **mypy deps**: Duplicated across 12 pre-commit hook configs

## Pure Bazel Structure Recommendations

### Current Deviations

1. **Mixed build systems**: Some packages have both `pyproject.toml` and `BUILD.bazel`
   - pyproject.toml should only contain pytest/tool config, not deps

2. **Standalone requirements.txt files**: Some packages have local requirements.txt
   - Should consolidate to `requirements_bazel.txt` at repo root

3. **External tool invocation**: Some targets shell out to external tools
   - Prefer Bazel-native rules when available

### Migration Path to Pure Bazel

1. Remove all `pip install` from CI/local workflows
2. Use `bazel run` for all Python scripts
3. Consolidate all Python deps to single `requirements_bazel.txt`
4. Replace shell scripts with `sh_binary` targets where appropriate
5. Migrate mypy to aspect_rules_lint
6. Remove duplicate ruff config from pyproject.toml

## Repo Health Recommendations

### Ongoing Maintenance

1. **Run audit periodically**: `./bazelization/audit.py`
2. **Add ruff_test to new packages**: Every BUILD.bazel with py_library should have ruff_test
3. **Keep requirements_bazel.txt updated**: Run `bazel run //:requirements.update` after adding deps
4. **Test with `bazel test //...`**: Ensure all non-manual tests pass before commits

### Pre-commit Integration

The `pre-commit` configuration should include:
```yaml
- repo: local
  hooks:
    - id: bazel-test
      name: bazel test
      entry: bazel test //...
      language: system
      pass_filenames: false
```

### CI Configuration

Recommended CI steps:
1. `bazel build //...` - Verify everything builds
2. `bazel test //...` - Run all tests
3. `bazel lint //...` - Run ruff linting (aspect_rules_lint)

## Commands Reference

```bash
bazel build //...           # Build everything
bazel test //...            # Test everything
bazel lint //...            # Lint with ruff (aspect_rules_lint)
bazel build //adgn:adgn     # Build specific package
bazel test //adgn:tests     # Test specific package
bazel run //:requirements.update  # Update requirements lock
```

## Known Issues

### rules_python lock() doesn't inherit --action_env

The `lock()` rule sets explicit `env` on `ctx.actions.run_shell()`, bypassing `--action_env`.

**Workaround:** Pass proxy env vars directly to `lock()` rule's `env` attribute.

### Python 3.13 Compatibility

Some packages require updates for Python 3.13:
- `homeassistant/iaqi`: Fixed `datetime.UTC` usage
- Watch for `datetime.datetime.utcnow()` deprecation warnings
