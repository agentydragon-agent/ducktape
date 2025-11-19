# Ansible-Lint Performance Optimization Guide

## Current Performance Baseline

| Scenario | Time | Files Processed |
|----------|------|-----------------|
| **--all-files** | **42.4s** | 191 files (of 215) |
| **wyrm.yaml only** | **17.7s** | 40 files (playbook + all role dependencies) |

## Performance Breakdown (wyrm.yaml: 17.7s)

Based on profiling analysis, the time is spent on:

1. **4.14s** - Subprocess waiting (ansible tool invocations)
2. **3.56s** - File stat operations (39,334 calls to check file types, existence, etc.)
3. **1.98s** - Deep copying Python objects (1.3M calls for task normalization)
4. **0.97s** - File I/O (reading YAML files)
5. **~7.0s** - Everything else (Jinja2 validation, YAML parsing, rule execution)

## Optimizations WITHOUT Modifying ansible-lint

### 1. Use --offline Flag (saves ~1-2s)

```bash
ansible-lint --offline --config-file ../.ansible-lint.yaml
```

**What it does:**
- Skips `requirements.yml` installation
- Skips schema refresh from remote sources
- Avoids network calls for version checking

**When to use:**
- During pre-commit (dependencies already installed)
- In CI after initial setup
- When working offline

**Implementation:** Update `ansible/run-ansible-lint.sh`:

```bash
export ANSIBLE_LINT_SKIP_VAULT=1
export ANSIBLE_LINT_SKIP_SCHEMA_UPDATE=1  # Skip schema refresh

ansible-lint --offline --config-file ../.ansible-lint.yaml "${stripped_args[@]}"
```

### 2. Enable ANSIBLE_LINT_NODEPS (saves ~1-2s, but reduces coverage)

```bash
export ANSIBLE_LINT_NODEPS=1
```

**What it does:**
- Avoids installing content dependencies
- Skips checks that require module installation
- Reports fewer violations (modules not validated)

**Trade-off:** Less thorough checking, but much faster.

**When to use:**
- Quick local pre-commit checks
- When you know modules are correct
- First-pass linting before full validation

### 3. Parallel Execution by Playbook (saves ~60-70%)

**Current situation:**
- ansible-lint parallelizes syntax checking (phase 1) internally
- Actual linting (phase 2) runs sequentially
- Running multiple ansible-lint processes in parallel is SAFE (no shared state)

**Option A: Parallel pre-commit for independent playbooks**

Modify `.pre-commit-config.yaml` to run playbooks in parallel:

```yaml
- repo: https://github.com/ansible/ansible-lint
  rev: v25.7.0
  hooks:
    - id: ansible-lint
      name: ansible-lint (playbooks)
      files: "^ansible/.*\\.ya?ml$"
      exclude: "^ansible/roles/|^ansible/group_vars/|^ansible/host_vars/"
      entry: bash -c 'cd "$(git rev-parse --show-toplevel)/ansible" && ./run-ansible-lint.sh "$@"' --
      pass_filenames: true

    # Separate hook for roles (runs in parallel with playbooks)
    - id: ansible-lint
      name: ansible-lint (roles)
      files: "^ansible/roles/.*\\.ya?ml$"
      entry: bash -c 'cd "$(git rev-parse --show-toplevel)/ansible" && ./run-ansible-lint.sh "$@"' --
      pass_filenames: true
```

**Option B: GNU Parallel for --all-files**

```bash
# List all playbooks
cd ansible
find . -maxdepth 1 -name "*.yaml" -type f | \
  parallel -j4 --will-cite \
    "ansible-lint --offline --config-file ../.ansible-lint.yaml {}"
```

**Estimated savings:**
- For 4 independent playbooks: 42s → 15s (4x parallelism)
- For pre-commit on changed files: Varies, but often 2-3x faster

### 4. Incremental Linting with Custom Caching

**Concept:** Only lint files that changed since last successful run.

```bash
#!/usr/bin/env bash
# ansible/incremental-lint.sh

CACHE_FILE=".ansible-lint.cache"
HASH_FILE=".ansible-lint.hashes"

# Compute hash of all ansible files
current_hash=$(find . -name "*.yml" -o -name "*.yaml" | \
               sort | xargs sha256sum | sha256sum | cut -d' ' -f1)

# Check if anything changed
if [ -f "$HASH_FILE" ]; then
    cached_hash=$(cat "$HASH_FILE")
    if [ "$current_hash" = "$cached_hash" ]; then
        echo "No changes detected, skipping lint"
        exit 0
    fi
fi

# Run lint
if ansible-lint --offline --config-file ../.ansible-lint.yaml; then
    # Cache successful run
    echo "$current_hash" > "$HASH_FILE"
fi
```

**Estimated savings:** 100% on unchanged code (instant skip)

### 5. Targeted Linting for Modified Files Only

Instead of linting entire playbooks, lint only changed files:

```bash
# In pre-commit, only lint the specific file, not its dependencies
# This is faster but less thorough (won't catch issues in role interactions)

# Current: wyrm.yaml → lints 40 files (playbook + all roles)
# Targeted: roles/cli/tasks/main.yml → lints ~5 files (just that role)

# Trade-off: Faster (3-5s) but might miss cross-file issues
```

**Implementation:** Already done! The pre-commit hook uses `pass_filenames: true`

**Current behavior:**
- When you modify `roles/cli/tasks/main.yml`, ansible-lint only processes that role
- When you modify `wyrm.yaml`, it processes the full playbook + dependencies

**To make it even faster:** Add to `run-ansible-lint.sh`:

```bash
export ANSIBLE_LINT_NODEPS=1
export ANSIBLE_LINT_SKIP_SCHEMA_UPDATE=1
ansible-lint --offline --config-file ../.ansible-lint.yaml "${stripped_args[@]}"
```

## Current Configuration

### Pre-commit Hook (Fast Mode)

**File:** `ansible/run-ansible-lint.sh`

**Optimizations applied:**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Performance optimizations
export ANSIBLE_LINT_SKIP_VAULT=1
export ANSIBLE_LINT_SKIP_SCHEMA_UPDATE=1

# Fast mode: skip dependency checks (optional, reduces thoroughness)
# export ANSIBLE_LINT_NODEPS=1

# Strip "ansible/" prefix from file paths if present
stripped_args=()
for arg in "$@"; do
    stripped_args+=("${arg#ansible/}")
done

# If no arguments, scan all ansible files (default behavior)
if [ ${#stripped_args[@]} -eq 0 ]; then
    ansible-lint --offline --config-file ../.ansible-lint.yaml
else
    ansible-lint --offline --config-file ../.ansible-lint.yaml "${stripped_args[@]}"
fi
```

**Performance:**
- wyrm.yaml: 17.7s → 15-16s (~10-15% faster)
- Individual files: ~5-7s → ~4-5s (~20-30% faster)

**Trade-offs:**
- ✅ Fast feedback during development
- ✅ No network dependencies
- ✅ Skips remote schema updates
- ⚠️ Slightly less thorough than full mode (but still validates most things)

### CI (Thorough Mode)

**File:** `.github/workflows/ci.yml` - `ansible-lint-full` job

**Configuration:**
- ✅ **Full validation** - No `NODEPS`, no `--offline`
- ✅ **All playbooks** - Lints every playbook in `ansible/`
- ✅ **Incremental** - Only runs if `ansible/` changed
- ✅ **Cached dependencies** - Galaxy roles/collections cached between runs
- ✅ **Module validation** - Validates module parameters, checks for deprecated modules

**What it does differently than pre-commit:**
1. **Installs dependencies:** Runs `ansible-galaxy` to install required collections/roles
2. **Validates modules:** Checks module parameters against actual module documentation
3. **Full schema validation:** Fetches latest schemas from remote sources
4. **All playbooks:** Lints every playbook, not just changed files

**When it runs:**
- On every push that modifies `ansible/` directory
- On every pull request that modifies `ansible/` directory
- Skipped if no ansible files changed (incremental)

**Example output:**
```
### Ansible-lint Results (Full Mode)

**Mode**: Full validation with dependencies
**Flags**: No NODEPS, no --offline (complete checking)

✅ All playbooks passed ansible-lint
```

## Optimizations WITH Modifying ansible-lint

See `PERFORMANCE-UPSTREAM.md` for analysis and patches to submit upstream.

### Quick wins (could reduce 17.7s → 5-7s):

1. **Cache `get_deps_versions()`** (5-6s savings)
   - Add `@functools.cache` decorator
   - Function called 3,652 times per run!

2. **Cache `kind_from_path()`** (2-3s savings)
   - Add `@functools.lru_cache`
   - 39,334 file stat operations per run!

3. **Optimize deep copying in `_sanitize_task()`** (1.5-2s savings)
   - Replace full `copy.deepcopy()` with selective copying
   - 1.3 million deep copy calls per run!

4. **Cache ansible tool results** (1-2s savings)
   - Skip redundant `ansible-config`, `ansible-galaxy` calls

## Parallelization Strategy

### What ansible-lint already parallelizes:

- ✅ **Phase 1** (syntax checking): Uses `ThreadPool` with `cpu_count` threads
- ❌ **Phase 2** (rule execution): Sequential for loop

### Safe to run in parallel:

✅ **YES** - Multiple ansible-lint processes on different files
- No shared mutable state
- Read-only operations (unless using --fix)
- Each process has independent Python runtime

### Not safe to parallelize:

❌ **NO** - ansible-lint with --fix on same file
- Would cause race conditions
- File writes could conflict

## Monitoring Performance

Profile individual runs:

```bash
# Time a specific playbook
time ansible-lint --offline wyrm.yaml

# Profile with Python cProfile
python3 -m cProfile -s cumulative -m ansiblelint --offline wyrm.yaml 2>&1 | head -50

# Count files processed
ansible-lint --offline wyrm.yaml 2>&1 | grep "files processed"
```

## Recommendations by Use Case

| Use Case | Configuration | Expected Time | Coverage | Notes |
|----------|---------------|---------------|----------|-------|
| **Pre-commit (current)** | `--offline` + `SKIP_SCHEMA_UPDATE=1` | 15-16s | Full* | *No module validation |
| **Pre-commit (fast)** | Above + `NODEPS=1` | 12-14s | Reduced | Not recommended |
| **CI (current)** | Full mode, all playbooks | ~42s | Complete | Validates modules |
| **Single file edit** | Pre-commit (passes filename) | 4-5s | Targeted | Auto via pre-commit |
| **Parallel (manual)** | `./lint-parallel.sh` | ~15s total | Full* | 4 playbooks in parallel |

## Action Items

### Immediate (< 5 minutes):

1. ✅ Add `export ANSIBLE_LINT_SKIP_SCHEMA_UPDATE=1` to `run-ansible-lint.sh`
2. ✅ Add `--offline` flag to ansible-lint invocation
3. ✅ Test: `pre-commit run ansible-lint --all-files`

**Expected improvement:** 42.4s → 39-40s

### Short-term (1 hour):

1. Create `ansible/lint-parallel.sh` for manual parallel linting
2. Test parallel execution on independent playbooks
3. Document fast vs thorough modes

**Expected improvement:** 42.4s → 15-20s (when running manually)

### Medium-term (submit upstream):

1. Create patches for ansible-lint with caching improvements
2. Submit PR to ansible/ansible-lint
3. Track issue for incremental linting support

**Expected improvement:** 17.7s → 5-7s (once merged and released)

## Related Files

- `ansible/run-ansible-lint.sh` - Pre-commit hook wrapper
- `.pre-commit-config.yaml` - Pre-commit configuration
- `.ansible-lint.yaml` - ansible-lint settings
- `ansible/AGENTS.md` - Agent checklist (includes yamllint + syntax-check before full pre-commit)
