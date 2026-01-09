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

### 📊 Summary

**Major achievement today**: Completed Phases 1 & 2 of bazelization roadmap

**Current pre-commit workflow** (`.pre-commit-config.yaml`):

1. **bazel-lint**: Combined ruff + ESLint aspects on Python/JS/TS files
2. **bazel-typecheck**: mypy aspect on Python files
3. **bazel-rust-check**: clippy + rustfmt aspects on Rust files
4. **bazel-format**: Unified auto-fix for all languages (ruff, prettier, rustfmt, shfmt, buildifier)

**Key improvements**:

- ✅ All linters now use Bazel aspects (no more test targets or bespoke scripts)
- ✅ Auto-formatting works for Python, JS/TS, Rust, shell, Bazel files
- ✅ Type checking (mypy) blocks commits
- ✅ Deleted 6 bespoke wrapper scripts (lint-staged.sh, run_eslint.sh, check-ansible-changes.sh, etc.)
- ✅ Consistent workflow: aspect for checking, //tools/format for fixing
- ✅ Simplified CI: inline path filtering instead of custom scripts

**Next steps** (Phase 3):

- Create unified `bazel check //...` command that runs all aspects
- Update CI to use unified command
- Simplify pre-commit to single check hook

### ✅ Fully Bazelized

| Tool             | Language     | Purpose    | Bazel Integration                                        | Pre-commit                   | CI                       | Notes                       |
| ---------------- | ------------ | ---------- | -------------------------------------------------------- | ---------------------------- | ------------------------ | --------------------------- |
| **ruff**         | Python       | Lint       | Aspect (`//tools/lint:linters.bzl%ruff`)                 | ✅ via `--config=lint`       | ✅ `--config=check`      | Aspect migration 2026-01-02 |
| **ruff format**  | Python       | Format     | Via `//tools/format`                                     | ✅ auto-fix                  | ✅                       | Added 2026-01-02            |
| **mypy**         | Python       | Type check | Aspect (`//tools/lint:linters.bzl%mypy_aspect`)          | ✅ via `--config=typecheck`  | ✅ `--config=check`      | Added 2026-01-02            |
| **ESLint**       | JS/TS/Svelte | Lint       | Aspect (`//tools/lint:linters.bzl%eslint`)               | ✅ via `--config=eslint`     | ✅ `--config=eslint`     | Added 2026-01-02            |
| **prettier**     | JS/TS/Svelte | Format     | Via `//tools/format`                                     | ✅ auto-fix                  | ✅ `--config=prettier`   | Added 2026-01-02            |
| **shfmt**        | Shell        | Format     | Via `//tools/format`                                     | ✅ auto-fix                  | ✅                       | Added 2026-01-02            |
| **buildifier**   | Bazel        | Format     | Via `//tools/format`                                     | ✅ auto-fix                  | ✅                       | Added 2026-01-02            |
| **svelte-check** | Svelte       | Type check | Test target                                              | ❌                           | ✅ test target           |                             |
| **clippy**       | Rust         | Lint       | Aspect (`@rules_rust//rust:defs.bzl%rust_clippy_aspect`) | ✅ via `--config=rust-check` | ✅ `--config=rust-check` | Added 2026-01-02            |
| **rustfmt**      | Rust         | Format     | Via `//tools/format` + aspect                            | ✅ auto-fix + check          | ✅ `--config=rust-check` | Added 2026-01-02            |
| **alejandra**    | Nix          | Format     | Test target                                              | ❌                           | ❌                       | Check-only                  |
| **yamllint**     | YAML         | Lint       | Test target (`//ansible:yamllint_test`)                  | ❌                           | ❌                       | Ansible only                |

### ⚠️ Partially Bazelized

| Tool                                | Language | Purpose | Issue                                                     | Pre-commit | CI  |
| ----------------------------------- | -------- | ------- | --------------------------------------------------------- | ---------- | --- |
| **ansible-playbook --syntax-check** | Ansible  | Syntax  | Custom shell script `ansible/scripts/run-syntax-check.sh` | ✅         | ✅  |
| **ansible-lint**                    | Ansible  | Lint    | Completely outside Bazel (manual pip install)             | ❌         | ✅  |

### ❌ Not Bazelized (Raw pre-commit-hooks)

| Hook                   | Purpose       | Issue                          |
| ---------------------- | ------------- | ------------------------------ |
| `no-commit-to-branch`  | Safety        | External pre-commit-hooks repo |
| `check-merge-conflict` | Safety        | External pre-commit-hooks repo |
| `check-ast`            | Python syntax | External pre-commit-hooks repo |
| `check-yaml`           | YAML syntax   | External pre-commit-hooks repo |
| `check-toml`           | TOML syntax   | External pre-commit-hooks repo |

---

## Major Asymmetries & Problems

### 1. **Pre-commit hooks use mixed approaches**

- Some hooks call Bazel (ruff, ESLint)
- Some use external repos (check-ast, check-yaml)
- Some use custom shell scripts (ansible-syntax-check)
- **Goal**: Everything should be `bazel test //...` or `bazel build --config=lint //...`

### 2. ~~**No auto-fix on commit**~~ ✅ RESOLVED (2026-01-02)

- ~~All formatters (prettier, rustfmt, alejandra, buildifier) are **check-only**~~
- ~~Pre-commit should **auto-fix** formatting issues~~
- ~~**Goal**: `bazel run //tools/format:fix` to auto-fix all formatting~~
- **DONE**: Pre-commit now runs `bazel run //tools/format` for auto-fix

### 3. ~~**Type checkers not in pre-commit**~~ ✅ RESOLVED (2026-01-02)

- ~~mypy aspect exists but not hooked into pre-commit~~
- ~~svelte-check not in pre-commit~~
- ~~**Goal**: Type errors should block commits~~
- **DONE**: mypy now runs via `--config=typecheck` in pre-commit

### 4. **Ansible tooling completely outside Bazel**

- ansible-lint uses manual pip install in CI
- No Bazel rules for Ansible
- **Goal**: Either Bazel-ize or document as intentional exception

### 5. ~~**CI config out of sync**~~ ✅ RESOLVED (2026-01-02)

- ~~CI runs `bazel test //props/frontend:eslint_test` but target doesn't exist~~
- ~~Now using aspects instead of test targets for ESLint~~
- ~~**Goal**: CI should match local workflow exactly~~
- **DONE**: CI now uses aspects (--config=lint, --config=rust-check), consolidated into bazel-build job

### 6. ~~**Lint-staged.sh is bespoke tooling**~~ ✅ RESOLVED (2026-01-02)

- ~~Custom script to map files → Bazel packages → ruff targets~~
- ~~Works but adds complexity~~
- ~~**Goal**: aspect_rules_lint should handle this automatically~~
- **DONE**: Deleted lint-staged.sh, ruff now uses aspects like other linters

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

### Phase 1: Pre-commit Integration ✅ COMPLETE (2026-01-02)

- [x] Wire ESLint aspect into pre-commit
- [x] SessionStart hook installs pre-commit
- [x] Add mypy aspect to pre-commit
- [x] Switch ruff to aspect approach
- [x] Add Rust clippy/rustfmt to pre-commit
- [ ] Add svelte-check to pre-commit
- [ ] Remove raw pre-commit-hooks, implement equivalents in Bazel

### Phase 2: Auto-fix Support ✅ COMPLETE (2026-01-02)

- [x] Use `//tools/format` target for auto-fix:
  - `ruff format` (Python)
  - `prettier --write` (JS/TS/Svelte/CSS/YAML)
  - `rustfmt` (Rust)
  - `shfmt` (shell scripts)
  - `buildifier -mode=fix` (Bazel files)
- [x] Hook formatters into pre-commit with auto-fix

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

### Phase 5: Cleanup ⚠️ IN PROGRESS

- [x] Remove `tools/hooks/lint-staged.sh` (rely on aspects)
- [x] Remove bespoke shell scripts (run_eslint.sh, run_prettier.sh, etc.)
- [x] Consolidate CI jobs (merged rust-lint into bazel-build)
- [x] Update CI config to use aspects (--config=lint, --config=rust-check)
- [ ] Create unified `bazel check //...` command (Phase 3 dependency)
- [ ] Simplify CI to single check command once unified command exists

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

1. ⚠️ **Pre-commit hook** is a single `bazel check //...` command (Currently: Multiple aspect configs)
2. ⚠️ **CI** runs identical `bazel check //...` command (Partially done: uses aspects, not yet unified command)
3. ✅ **No manual tool invocations** (no `ruff`, `mypy`, `npm run lint`, etc.) - ALL go through Bazel
4. ✅ **Auto-fix on commit** for all formatters (ruff, prettier, rustfmt, shfmt, buildifier)
5. ✅ **Type errors block commits** (mypy in pre-commit)
6. ✅ **Zero bespoke shell scripts** in `tools/hooks/` (lint-staged.sh deleted)
7. ✅ **Hermetic builds** - all tools fetched/managed by Bazel
8. ✅ **Fast incremental checks** - Bazel caching works correctly

**Progress: 6/8 complete** (75%)

**Recent improvement**: CI now consolidated - bazel-build runs all aspect-based linting (Python, JS/TS, Rust) in single job

---

## Run Script Analysis

### Scripts Eliminated (Pure Bazel Wrappers) ✅ DONE

These wrapper scripts have been deleted as they're obsolete with aspects:

| Script                                     | Purpose                          | Status     | Replacement                       |
| ------------------------------------------ | -------------------------------- | ---------- | --------------------------------- |
| `tools/lint/run_eslint.sh`                 | ESLint wrapper for sh_test       | ✅ DELETED | ESLint aspect                     |
| `tools/lint/run_prettier.sh`               | Prettier wrapper for sh_test     | ✅ DELETED | Prettier in //tools/format        |
| `tools/yamllint/run_yamllint.sh`           | Yamllint wrapper for sh_test     | ✅ DELETED | Test target (Ansible-specific)    |
| `tools/nix/run_alejandra.sh`               | Alejandra wrapper                | ✅ DELETED | Test target                       |
| `tools/hooks/lint-staged.sh`               | Maps files→packages→ruff targets | ✅ DELETED | Ruff aspect handles automatically |
| `.github/scripts/check-ansible-changes.sh` | Check if ansible/ changed        | ✅ DELETED | Inline git diff in CI workflow    |

### Remaining Scripts With Business Logic

These contain significant logic beyond just running a tool:

| Script                                | Purpose                              | Status       | Notes                                                        |
| ------------------------------------- | ------------------------------------ | ------------ | ------------------------------------------------------------ |
| `ansible/scripts/run-syntax-check.sh` | Filter playbooks vs other YAML files | Keep for now | Complex logic to identify playbooks; could become Bazel rule |
| `.github/scripts/run-ansible-lint.sh` | Run ansible-lint on all playbooks    | Keep for now | CI uses inline path filtering; script runs the actual lint   |

### Scripts That Are Not Build Infrastructure

These are application/example scripts, not build tooling:

| Script                                  | Purpose                   | Keep?   |
| --------------------------------------- | ------------------------- | ------- |
| `sandboxed_jupyter/examples/run_one.sh` | Example reproducer script | **YES** |

**Status**:

1. ✅ **Wrapper scripts deleted**: All in `tools/lint/`, `tools/yamllint/`, `tools/nix/`, `tools/hooks/` - obsolete with aspects
2. ⚠️ **Ansible scripts remain**: Complex logic makes them harder to migrate to Bazel
3. ✅ **Application scripts preserved**: Example/reproducer scripts kept as intended

---

## Notes

- **SessionStart hook** (`claude_web_hooks/session_start.py`) currently:

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
          args: ["check", "//..."]
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
