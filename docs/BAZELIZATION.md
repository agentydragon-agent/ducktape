# Bazelization Progress & Goals

This document tracks the ongoing effort to fully Bazelizing all build, lint, type check, format, and test workflows.

## Primary Goal

**All development workflows should go through Bazel with zero manual/bespoke tooling.**

Specifically:
1. **SessionStart hook** installs pre-commit hook
2. **Pre-commit hook** delegates to Bazel aspects
3. **Bazel aspects** run lint/format/type checks with **auto-fix** where possible
4. **CI (GitHub Actions)** runs identical Bazel commands
5. **No manual invocations** of ruff, mypy, eslint, prettier, npm, etc.

This ensures:
- Hermetic, reproducible builds
- Consistent behavior across local dev, pre-commit, and CI
- Single source of truth for tooling configuration
- Automatic caching and incremental builds

---

## Current State (2026-01-02)

### ✅ Fully Bazelized

| Tool | Language | Purpose | Bazel Integration | Pre-commit | CI | Notes |
|------|----------|---------|-------------------|------------|----|----|
| **ruff** | Python | Lint | Aspect (`//tools/lint:linters.bzl%ruff`) | ✅ via `lint-staged.sh` | ✅ `--config=check` | |
| **mypy** | Python | Type check | Aspect (`//tools/lint:linters.bzl%mypy_aspect`) | ❌ | ✅ `--config=check` | Not in pre-commit |
| **ESLint** | JS/TS/Svelte | Lint | Aspect (`//tools/lint:linters.bzl%eslint`) | ✅ direct | ✅ `--config=eslint` | Just added 2026-01-02 |
| **Prettier** | JS/TS/Svelte | Format | Test target (sh_test) | ❌ | ✅ test target | Check-only, no auto-fix |
| **svelte-check** | Svelte | Type check | Test target | ❌ | ✅ test target | |
| **clippy** | Rust | Lint | Aspect (`@rules_rust//rust:defs.bzl%rust_clippy_aspect`) | ❌ | ✅ `--config=rust-check` | |
| **rustfmt** | Rust | Format | Aspect (`@rules_rust//rust:defs.bzl%rustfmt_aspect`) | ❌ | ✅ `--config=rust-check` | Check-only |
| **alejandra** | Nix | Format | Test target | ❌ | ❌ | Check-only |
| **yamllint** | YAML | Lint | Test target (`//ansible:yamllint_test`) | ❌ | ❌ | Ansible only |
| **buildifier** | Bazel | Format | Via multitool | ❌ | ❌ | |

### ⚠️ Partially Bazelized

| Tool | Language | Purpose | Issue | Pre-commit | CI |
|------|----------|---------|-------|------------|-----|
| **ansible-playbook --syntax-check** | Ansible | Syntax | Custom shell script `ansible/scripts/run-syntax-check.sh` | ✅ | ✅ |
| **ansible-lint** | Ansible | Lint | Completely outside Bazel (manual pip install) | ❌ | ✅ |

### ❌ Not Bazelized (Raw pre-commit-hooks)

| Hook | Purpose | Issue |
|------|---------|-------|
| `no-commit-to-branch` | Safety | External pre-commit-hooks repo |
| `check-merge-conflict` | Safety | External pre-commit-hooks repo |
| `check-ast` | Python syntax | External pre-commit-hooks repo |
| `check-yaml` | YAML syntax | External pre-commit-hooks repo |
| `check-toml` | TOML syntax | External pre-commit-hooks repo |

---

## Major Asymmetries & Problems

### 1. **Pre-commit hooks use mixed approaches**
- Some hooks call Bazel (ruff, ESLint)
- Some use external repos (check-ast, check-yaml)
- Some use custom shell scripts (ansible-syntax-check)
- **Goal**: Everything should be `bazel test //...` or `bazel build --config=lint //...`

### 2. **No auto-fix on commit**
- All formatters (prettier, rustfmt, alejandra, buildifier) are **check-only**
- Pre-commit should **auto-fix** formatting issues
- **Goal**: `bazel run //tools/format:fix` to auto-fix all formatting

### 3. **Type checkers not in pre-commit**
- mypy aspect exists but not hooked into pre-commit
- svelte-check not in pre-commit
- **Goal**: Type errors should block commits

### 4. **Ansible tooling completely outside Bazel**
- ansible-lint uses manual pip install in CI
- No Bazel rules for Ansible
- **Goal**: Either Bazel-ize or document as intentional exception

### 5. **CI config out of sync**
- CI runs `bazel test //props/frontend:eslint_test` but target doesn't exist
- Now using aspects instead of test targets for ESLint
- **Goal**: CI should match local workflow exactly

### 6. **Lint-staged.sh is bespoke tooling**
- Custom script to map files → Bazel packages → ruff targets
- Works but adds complexity
- **Goal**: aspect_rules_lint should handle this automatically

### 7. **No unified "check everything" command**
- Have to remember `--config=check`, `--config=eslint`, `--config=rust-check`, test targets
- **Goal**: Single `bazel check //...` runs all linters/formatters/type checkers

### 8. **Formatters don't share configuration**
- Prettier config in `props/frontend/.prettierrc`
- Rustfmt config in `finance/worthy/rustfmt.toml`
- Alejandra has no config (opinionated)
- **Goal**: Centralized formatting config where possible

---

## Roadmap to Full Bazelization

### Phase 1: Pre-commit Integration (CURRENT)
- [x] Wire ESLint aspect into pre-commit
- [x] SessionStart hook installs pre-commit
- [ ] Add mypy aspect to pre-commit
- [ ] Add svelte-check to pre-commit
- [ ] Add Rust clippy/rustfmt to pre-commit (if working on Rust)
- [ ] Remove raw pre-commit-hooks, implement equivalents in Bazel

### Phase 2: Auto-fix Support
- [ ] Create `//tools/format:fix` target that runs:
  - `prettier --write`
  - `rustfmt` (not just check)
  - `alejandra` (not just check)
  - `buildifier -mode=fix`
- [ ] Add `--fix` flag to ruff aspect
- [ ] Hook formatters into pre-commit with auto-fix

### Phase 3: Unified Check Command
- [ ] Create `//tools:check` target or `.bazelrc` config
- [ ] Single command: `bazel check //...` runs:
  - All linters (ruff, eslint, clippy, yamllint)
  - All type checkers (mypy, svelte-check)
  - All formatters in check mode (prettier, rustfmt, alejandra, buildifier)
- [ ] Pre-commit uses this unified command
- [ ] CI uses this unified command

### Phase 4: Ansible Bazelization (or Exception)
- [ ] Investigate rules_ansible or custom rules
- [ ] If not feasible, document Ansible as intentional exception with rationale
- [ ] Minimize custom scripting (ansible/scripts/run-syntax-check.sh)

### Phase 5: Cleanup
- [ ] Remove `tools/hooks/lint-staged.sh` (rely on aspects)
- [ ] Remove bespoke shell scripts
- [ ] Consolidate CI jobs into single Bazel command
- [ ] Update CI config to match current implementation

---

## Bazel Configs Reference

From `.bazelrc`:

```bash
# Lint (Python ruff + JS/TS ESLint)
bazel build --config=lint //...

# Type check (Python mypy)
bazel build --config=typecheck //...

# Combined Python lint + type
bazel build --config=check //...

# Rust lint + format
bazel build --config=rust-check //...

# ESLint only
bazel build --config=eslint //...
```

**Goal**: Simplify to:
```bash
# Check everything (lint + type + format)
bazel check //...

# Fix everything (auto-fix formatting)
bazel fix //...
```

---

## Success Criteria

Bazelization is complete when:

1. ✅ **Pre-commit hook** is a single `bazel check //...` command
2. ✅ **CI** runs identical `bazel check //...` command
3. ✅ **No manual tool invocations** (no `ruff`, `mypy`, `npm run lint`, etc.)
4. ✅ **Auto-fix on commit** for all formatters
5. ✅ **Type errors block commits**
6. ✅ **Zero bespoke shell scripts** in `tools/hooks/`
7. ✅ **Hermetic builds** - all tools fetched/managed by Bazel
8. ✅ **Fast incremental checks** - Bazel caching works correctly

---

## Run Script Analysis

### Scripts That Should Be Eliminated (Pure Bazel Wrappers)

These are thin wrappers that just `cd` and `exec` - they exist to work around Bazel test infrastructure limitations. With aspects, they're unnecessary:

| Script | Purpose | Can Eliminate? | Replacement |
|--------|---------|----------------|-------------|
| `tools/lint/run_eslint.sh` | ESLint wrapper for sh_test | **YES** | ESLint aspect (already implemented) |
| `tools/lint/run_prettier.sh` | Prettier wrapper for sh_test | **YES** | Prettier aspect or direct bazel run |
| `tools/yamllint/run_yamllint.sh` | Yamllint wrapper for sh_test | **YES** | Yamllint aspect |
| `tools/nix/run_alejandra.sh` | Alejandra wrapper | **YES** | Direct multitool invocation |

**Action**: Replace sh_test wrappers with aspects or direct tool invocations.

### Scripts With Business Logic (Keep or Migrate to Starlark)

These contain significant logic beyond just running a tool:

| Script | Purpose | Keep? | Notes |
|--------|---------|-------|-------|
| `tools/hooks/lint-staged.sh` | Maps files→packages→ruff targets | **NO** | aspect_rules_lint should handle file filtering automatically |
| `ansible/scripts/run-syntax-check.sh` | Filter playbooks vs other YAML files | **MAYBE** | Complex logic to identify playbooks; could become Bazel rule |
| `.github/scripts/run-ansible-lint.sh` | Run ansible-lint on all playbooks | **MIGRATE** | Should be `bazel test //ansible:lint` |

### Scripts That Are Not Build Infrastructure

These are application/example scripts, not build tooling:

| Script | Purpose | Keep? |
|--------|---------|-------|
| `sandboxed_jupyter/examples/run_one.sh` | Example reproducer script | **YES** |

**Recommendation**:
1. **Remove immediately**: All wrapper scripts in `tools/lint/`, `tools/yamllint/`, `tools/nix/` - they're obsolete with aspects
2. **Replace next**: `tools/hooks/lint-staged.sh` - aspect-based filtering makes this unnecessary
3. **Migrate or document**: Ansible scripts - either create proper Bazel rules or document as intentional exception
4. **Keep**: Application-specific scripts outside of build infrastructure

---

## Notes

- **SessionStart hook** (`claude_web_hooks/src/claude_web_hooks/session_start.py`) currently:
  - Installs bazelisk (✅)
  - Sets up Bazel proxy for TLS-inspecting proxy (✅)
  - Installs pre-commit hook via `pre-commit install` (✅)
  - Does NOT ensure pre-commit delegates to Bazel properly (❌)

- **Pre-commit config** (`.pre-commit-config.yaml`) should ultimately be:
  ```yaml
  repos:
    - repo: local
      hooks:
        - id: bazel-check
          name: bazel check //...
          entry: bazel
          args: ['check', '//...']
          language: system
          pass_filenames: false
  ```

- **CI** (`.github/workflows/ci.yml`) should ultimately be:
  ```yaml
  - name: Check everything
    run: bazel check //...

  - name: Test everything
    run: bazel test //...
  ```
