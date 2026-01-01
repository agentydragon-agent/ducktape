# Bazel Migration Status

## Full Bazel Vision

The end-state is a **fully Bazel-managed repository** where:

### All Builds and Tests via Bazel
- `bazel build //...` builds everything (Python, Rust, JS/TS frontends, Docker images)
- `bazel test //...` runs all tests (unit, integration, e2e)
- No direct `pytest`, `npm test`, `cargo test` invocations outside Bazel

### All Linting via Bazel Aspects
- `bazel lint //...` covers all languages in one command:
  - Python: ruff (done), mypy (done)
  - Rust: clippy, rustfmt (done)
  - JS/TS: eslint (done), prettier (done), svelte-check (done)
  - Bazel: buildifier (done)
  - YAML: yamllint (for ansible/)
  - Nix: alejandra
- No separate pre-commit framework; git hook calls `bazel lint` directly

### Docker Images via rules_oci
- All container images built with `bazel build //docker/...:image`
- Deterministic, cacheable, layer-optimized builds
- No `docker build` commands in development or CI

### Single Dependency Source
- Python: `requirements_bazel.txt` → pip.parse lockfile
- JS/TS: `pnpm-lock.yaml` → npm_translate_lock
- Rust: `Cargo.lock` → crate_universe
- No per-package requirements.txt or pyproject.toml dependencies

### Simplified Package Structure
- Flat layout (no `src/` nesting) since Bazel handles packaging
- Tests colocated with production code (`module.py` + `module_test.py`)
- Fewer packages, Bazel visibility for layering instead of pyproject boundaries

### What Stays Outside Bazel
- Ansible (managed by Ansible Galaxy)
- Nix configuration (inherently non-Bazel)
- Website (Haskell/stack, very slow cold builds)

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
- Session start hooks for Claude Code web: Bazel proxy + git pre-commit hook installation
- Git pre-commit hook (`tools/hooks/pre-commit`) runs `bazel lint` on staged files
- `aspect_rules_lint` integrated for ruff linting (`bazel lint //...`)
- Node.js frontends migrated to rules_js (`props/frontend`, `rspcache/admin_ui`)
- Mypy integrated via rules_mypy (`--config=typecheck`)
- Rust linting (clippy/rustfmt) integrated via rules_rust (`bazel lint //finance/...`)
- Removed all re-export patterns from Python packages (direct imports only)
- ESLint integrated into `bazel lint //...` via aspect_rules_lint
- Buildifier targets: `bazel run //tools/lint:buildifier` (fix) and `buildifier.check`
- Documentation updated to be Bazel-first (AGENTS.md, README.md files)
- Consolidated duplicate ruff config (removed from per-package pyproject.toml)
- CI workflow updated to run `bazel lint //...` in addition to `bazel build` and `bazel test`

### In Progress / Partial

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

## Hook Lifecycle

This repository uses two types of hooks:
1. **Git hooks** - Run on git operations (pre-commit)
2. **Claude Code session hooks** - Run when Claude Code web sessions start

### Git Pre-commit Hook

**Installation:**
```bash
ln -sf ../../tools/hooks/pre-commit .git/hooks/pre-commit
```

**What it does:**
1. Gets staged Python files from git (`--diff-filter=ACM`)
2. Uses `bazel query attr('srcs', ...)` to find targets containing those files
3. Runs `bazel lint` on unique packages via Aspect CLI

**Requirements:**
- Aspect CLI (provides `bazel lint` command, installed via Bazelisk)
- Ruff binary from `tools/multitool/lockfile.json`

**The Bazel query:**
```bash
# Build regex from staged files, query for targets with matching srcs
PATTERN=$(echo "$STAGED_PY" | sed 's/\./\\./g' | tr '\n' '|' | sed 's/|$//')
bazel query "attr('srcs', '.*($PATTERN).*', //...)" --output=package
```

**Flow:**
```
git commit → pre-commit hook → bazel query → bazel lint //pkg1:all //pkg2:all → pass/fail
```

### Claude Code Session Start Hook

**Configuration:** `.claude/settings.json`
```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "PYTHONPATH=claude_web_hooks/src python3 -m claude_web_hooks.session_start"
      }]
    }]
  }
}
```

**What it does:**
1. Installs Bazelisk to `~/.cache/bazel-proxy/bazelisk`
2. Writes proxy credentials to `~/.cache/bazel-proxy/upstream_proxy`
3. Starts local proxy at `localhost:18081` (handles auth to upstream)
4. Extracts TLS inspection CA via openssl to upstream
5. Creates Java truststore with proxy CA at `~/.cache/bazel-proxy/cacerts.jks`
6. Creates combined CA bundle at `~/.cache/bazel-proxy/combined_ca.pem`
7. Writes `~/.cache/bazel-proxy/bazelrc` with proxy settings
8. Installs bazel wrapper at `~/.cache/bazel-proxy/bin/bazel`
9. Installs git pre-commit hook (`tools/hooks/pre-commit` → `.git/hooks/pre-commit`)
10. Exports PATH to wrapper via `CLAUDE_ENV_FILE`

**Package structure:**
```
claude_web_hooks/
├── src/claude_web_hooks/
│   ├── session_start.py      # Entry point
│   ├── bazelisk_setup.py     # Bazelisk + wrapper installation
│   ├── bazel_proxy_setup.py  # Proxy, CA, truststore setup
│   └── proxy.py              # Async proxy server (stdlib only)
```

**Files created:**
| Path | Purpose |
|------|---------|
| `~/.cache/bazel-proxy/bazelisk` | Bazelisk binary |
| `~/.cache/bazel-proxy/bin/bazel` | Wrapper that sets proxy env vars |
| `~/.cache/bazel-proxy/upstream_proxy` | Upstream proxy URL (refreshable) |
| `~/.cache/bazel-proxy/proxy.pid` | Proxy daemon PID |
| `~/.cache/bazel-proxy/cacerts.jks` | Java truststore with proxy CA |
| `~/.cache/bazel-proxy/combined_ca.pem` | System CAs + proxy CA |
| `~/.cache/bazel-proxy/bazelrc` | Bazel proxy configuration |
| `~/.bazelrc` | try-import for proxy bazelrc |

**Flow:**
```
Claude Code web start
  → SessionStart hook
  → session_start.py main()
  → bazelisk_setup.install_bazelisk()
  → bazel_proxy_setup.setup_bazel_proxy()
    → _update_proxy_credentials()
    → _start_proxy_server()
    → _extract_proxy_ca()
    → _create_java_truststore()
    → _create_combined_ca_bundle()
    → _write_bazel_config()
  → bazelisk_setup.install_wrapper()
  → Write CLAUDE_ENV_FILE (PATH, env vars)
```

### Bazel Module Extension for Proxy

The `tools/proxy_config/defs.bzl` module extension generates `@proxy_config//:proxy_env.bzl`:

- **On Claude Code web:** Detects proxy by checking if `~/.cache/bazel-proxy/combined_ca.pem` exists
- **On local dev:** Empty `PROXY_ENV = {}`

This allows BUILD files to use proxy env vars without hardcoding.

### Proxy Config Architecture

The proxy config is set in two places:

| Location | Purpose | Set By |
|----------|---------|--------|
| `~/.cache/bazel-proxy/bin/bazel` wrapper | For Bazelisk downloading Bazel | `bazelisk_setup.install_wrapper()` |
| `~/.cache/bazel-proxy/bazelrc` | For build actions (pip, uv) | `bazel_proxy_setup._write_bazel_config()` |

The module extension detects proxy config by checking if `~/.cache/bazel-proxy/combined_ca.pem` exists
(created by session hook), rather than reading environment variables.

## Linter Configuration

### Ruff Version and Lockfile

Ruff is managed via `rules_multitool` with a custom lockfile:

**Location:** `tools/multitool/lockfile.json`

**Current version:** 0.14.0 (aspect_rules_lint bundles 0.8.3, we override for newer features)

**Lockfile format:**
```json
{
  "ruff": {
    "binaries": [
      {
        "kind": "archive",
        "url": "https://github.com/astral-sh/ruff/releases/download/0.14.0/ruff-x86_64-unknown-linux-musl.tar.gz",
        "sha256": "...",
        "os": "linux",
        "cpu": "x86_64"
      }
      // ... other platforms
    ]
  }
}
```

**To update ruff:**
1. Check latest release at https://github.com/astral-sh/ruff/releases
2. Update URLs and sha256 hashes in `tools/multitool/lockfile.json`
3. Test with `bazel lint //...`

**How it integrates:**
```
MODULE.bazel
  → bazel_dep(name = "aspect_rules_lint")
  → multitool.hub(lockfile = "//tools/multitool:lockfile.json")

tools/lint/linters.bzl
  → lint_ruff_aspect(binary = "@multitool//tools/ruff")

BUILD.bazel files
  → ruff_test(name = "ruff", srcs = [":my_lib"])
```

### Ruff Configuration

**Location:** `ruff.toml` (root)

**Key settings:**
- `target-version = "py312"` - Python 3.12+ modern syntax
- `line-length = 120` - Wider lines than PEP 8 default
- Enabled rule categories: E, F, PLC/PLE/PLR/PLW, UP, FA, FURB, I, B, COM, C4, PT, SIM, N, RUF

**Per-file ignores** are in `ruff.toml` (not scattered in pyproject.toml files):
- `**/conftest.py` - Late imports allowed
- `**_det_*.py` - AST visitor naming allowed
- FastAPI patterns - `B008` for dependency injection

### Why Custom Lockfile?

`aspect_rules_lint` bundles ruff but uses an older version. The custom lockfile:
- Allows using latest ruff with new rules
- Provides explicit version pinning
- Works across all platforms (linux/macos, x64/arm64)

### Mypy Configuration

**Aspect:** `//tools/lint:linters.bzl%mypy_aspect`
**Config:** `mypy.ini` (root)

**Running mypy via Bazel:**
```bash
# Type check specific target
bazel build --config=typecheck //adgn:adgn

# Type check all Python targets
bazel build --config=typecheck //...

# Combined lint + typecheck
bazel build --config=check //...
```

**Key settings in mypy.ini:**
- `follow_imports = silent` - Only report errors in explicitly passed files
- `ignore_missing_imports = True` - Packages without stubs get lenient treatment
- Packages with `py.typed` (rich, structlog, aiohttp, aiodocker) ARE type-checked
  - API misuse in our code will be caught
- Packages with broken stubs (numpy, pandas, rpds) have `ignore_errors = True`
  - We still use their type info, just don't report internal stub errors

**Type checking behavior:**
- OUR code using typed packages → errors caught
- OUR code using untyped packages → no type info (ignore_missing_imports)
- Errors WITHIN external packages → suppressed

**Integration with rules_mypy:**
- Uses `rules_mypy` v0.40.0 for the mypy aspect
- Mypy runs on each py_library target with its transitive deps available
- Caches are propagated between targets for faster incremental checks

## Action Items

### High Priority

1. **Enable remote cache write in CI**
   - Currently read-only (`--remote_upload_local_results=false`)
   - Enable for main branch for better cache hit rates

2. **Migrate Docker images to rules_oci**
   - Start with `docker/runtime/Dockerfile` (most frequently built)
   - Then: `docker/llm/properties-critic/Dockerfile`
   - Evaluate complexity vs benefits for remaining images

3. **Fix ember_evals missing modules**
   - Add missing .kubernetes, .matrix, .steps, .models submodules
   - Or remove if abandoned

### Medium Priority

4. **Bazelify remaining Python files (54 not in targets)**
   - `inventree_utils/` (23 files) - create BUILD.bazel
   - `llm/` examples/scripts (6 files) - add to srcs or mark as data
   - `experimental/ember_evals/` (5 files) - fix or remove
   - Others: helm chart scripts, trilium scripts, etc.

5. **Add yamllint aspect for ansible/**
   - YAML linting via Bazel aspects
   - Remove yamllint from pre-commit hooks

6. **Bazelize frontend build/dev (props/frontend)**
   - Currently: `pnpm run build` (vite build), `pnpm run dev` (vite dev)
   - Target: `bazel build //props/frontend:bundle`, `bazel run //props/frontend:dev`
   - Use rules_js for vite integration
   - Eliminates heterogeneity: Python fully Bazel, JS/TS currently split
   - Note: Linting already Bazelized (prettier, svelte-check, eslint)

### Low Priority / Evaluate

7. **Rust crates via crate_universe**
   - `finance/worthy/` currently uses Cargo directly
   - Evaluate rules_rust crate_universe vs keeping Cargo

8. **Website (Haskell/stack)**
   - Extremely slow cold builds
   - Keep `stack build` outside Bazel for now

### Structural Improvements (do incrementally)

9. **Colocate tests with production code**
   - Move `tests/test_foo.py` → `src/pkg/foo_test.py`
   - Simpler BUILD files, easier to see coverage gaps

10. **Flatten package layouts**
    - Remove `src/` nesting (Bazel handles packaging)
    - Simpler paths in BUILD.bazel files

11. **Package consolidation**
    - Consider merging `mcp_infra/` into `adgn/`
    - Consider merging `agent_core/` into `adgn/`
    - Use Bazel visibility instead of package boundaries

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

### Flat Package Layout

Current: nested `src/` layout per PEP 517/518 conventions
Target: flat layout since Bazel handles packaging

```
# Current (nested src/)
package_name/
├── pyproject.toml
├── src/package_name/
│   └── module.py
└── tests/

# Target (flat)
package_name/
├── BUILD.bazel
├── module.py
├── module_test.py
└── pyproject.toml  # pytest config only
```

Benefits:
- Simpler paths in BUILD.bazel (no `src/` prefix)
- Clearer what's in the package
- Bazel visibility rules replace package boundaries

### Package Consolidation

Current: Many separate pyproject.toml packages with workspace references
Target: Fewer packages, Bazel visibility for layering

Rationale:
- Bazel `visibility` attribute enforces layering without pyproject boundaries
- Fewer packages = simpler dependency management
- No need for uv workspace for internal deps

Candidates for consolidation:
- `mcp_infra/` could merge into `adgn/`
- `agent_core/` could merge into `adgn/`
- Small experimental packages into `experimental/` monolith

Keep separate:
- Packages with different deployment targets (container vs host)
- Packages with genuinely different dependency sets

### JS/TS Linting via Bazel Aspects

Current: pre-commit hooks shell out to npm/pnpm for eslint/prettier
Target: Bazel aspects like ruff, integrated into `bazel lint //...`

**Blocker: rules_js artifact prefix conflict**

When creating a `js_binary` for eslint in the same package as `npm_link_all_packages`,
Bazel errors with "artifact prefix conflict" because:
- `npm_link_all_packages` creates `:node_modules/eslint` directory target
- `js_binary` entry_point creates `:node_modules/eslint/bin/eslint.js` file target
- These paths conflict (one is prefix of the other)

**Recommended solution (from aspect rules_lint docs):**

The `aspect_rules_lint` documentation recommends creating the eslint binary via
the package_json helper, not directly in the frontend package:

```starlark
# tools/lint/BUILD.bazel
load("@npm//:eslint/package_json.bzl", eslint_bin = "bin")
eslint_bin.eslint_binary(name = "eslint")
```

Then reference it in the linter aspect:
```starlark
# tools/lint/linters.bzl
eslint = lint_eslint_aspect(
    binary = Label("//tools/lint:eslint"),
    configs = [Label("//:eslintrc")],
)
```

This pattern works because:
1. The eslint binary lives in `tools/lint/`, not in the frontend package
2. `npm_translate_lock` with `bins = {"eslint": {"eslint": "./bin/eslint.js"}}`
   creates the `package_json.bzl` with the `bin` helper

**Required MODULE.bazel changes:**
```starlark
npm.npm_translate_lock(
    name = "npm",
    pnpm_lock = "//:pnpm-lock.yaml",
    bins = {
        "eslint": {"eslint": "./bin/eslint.js"},
    },
    public_hoist_packages = {
        "@eslint/js": ["props/frontend"],
        "globals": ["props/frontend"],
        "typescript-eslint": ["props/frontend"],
    },
)
```

**Current state:**
- `lint_eslint_aspect` defined in `tools/lint/linters.bzl` (ready)
- `.bazelrc` has `--config=eslint` (ready)
- TODO: Add `bins` config to npm_translate_lock
- TODO: Create eslint binary in `tools/lint/BUILD.bazel`
- TODO: Test the full eslint flow

**For now:** Use `npm run lint` in frontend directories via pre-commit hooks.

**References:**
- [rules_lint ESLint docs](https://docs.aspect.build/rulesets/aspect_rules_lint/docs/linting/)
- [rules_lint example linters.bzl](https://github.com/aspect-build/rules_lint/blob/main/example/tools/lint/linters.bzl)
- [rules_js troubleshooting](https://docs.aspect.build/rulesets/aspect_rules_js/docs/troubleshooting/)

Benefits (once working):
- Single `bazel lint //...` command for all languages
- Consistent caching/incrementality
- Same infrastructure for CI and local dev

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
| mypy | `mypy.ini` (root) | `bazel build --config=typecheck //...` via rules_mypy |
| buildifier | `tools/lint/BUILD.bazel` | `bazel run //tools/lint:buildifier` |
| yamllint | `.yamllint.yaml` | Not yet (pre-commit framework) |
| alejandra | Nix files | Not yet (pre-commit framework) |
| ESLint | `props/frontend/eslint.config.js` | `bazel lint //...` via aspect_rules_lint |
| Prettier | `props/frontend/.prettierrc` | `bazel test //props/frontend:prettier_test` |
| svelte-check | `props/frontend/tsconfig.json` | `bazel test //props/frontend:svelte_check_test` |

### Pre-commit Framework (`.pre-commit-config.yaml`) — DEPRECATED

**Note:** The pre-commit framework is being deprecated in favor of the Bazel-based git hook at
`tools/hooks/pre-commit`. The git hook runs `bazel lint` on staged files, which covers ruff and mypy.

The `.pre-commit-config.yaml` file still exists for:
- Hooks not yet migrated to Bazel (yamllint, alejandra)
- Safety checks (no-commit-to-branch, check-merge-conflict, syntax validation)
- Ansible syntax checking (ansible-syntax-check)

**Migration status for pre-commit hooks:**

| Hook | Purpose | Bazel Equivalent | Status |
|------|---------|------------------|--------|
| `no-commit-to-branch` | Block commits to main | N/A (git hook) | Keep in pre-commit |
| `check-ast` | Valid Python syntax | `bazel build` catches | Redundant |
| `check-yaml` | Valid YAML | N/A | Keep in pre-commit |
| `check-toml` | Valid TOML | N/A | Keep in pre-commit |
| `yamllint` | YAML style | TODO: yamllint aspect | Keep in pre-commit |
| `ansible-syntax-check` | Ansible validation | N/A | Keep in pre-commit |
| `ruff-check` | Linting | `bazel lint //...` | ✅ Migrated |
| `ruff-format` | Formatting | `bazel lint //...` | ✅ Migrated |
| `mypy` (12 configs) | Type checking | `bazel build --config=typecheck` | ✅ Migrated |
| `buildifier` | BUILD formatting | `bazel run //tools/lint:buildifier` | ✅ Migrated |
| `alejandra` | Nix formatting | N/A (nix-specific) | Keep in pre-commit |
| `eslint` | JS/TS linting | `bazel lint //...` | ✅ Migrated |
| `prettier` | JS/TS formatting | `bazel test //props/frontend:prettier_test` | ✅ Migrated |
| `svelte-check` | Svelte types | `bazel test //props/frontend:svelte_check_test` | ✅ Migrated |

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

### Git Pre-commit Hook (Recommended)

Install the Bazel-based git hook instead of using the pre-commit framework:

```bash
ln -sf ../../tools/hooks/pre-commit .git/hooks/pre-commit
```

This hook runs `bazel lint` on staged Python files. For Claude Code web sessions,
the session start hook installs this automatically.

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
