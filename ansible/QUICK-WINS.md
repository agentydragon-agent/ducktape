# Ansible-Lint Quick Performance Wins

## Already Applied ✅

### 1. Pre-commit: Fast Syntax Check Only

**Changed to `ansible-playbook --syntax-check`** instead of full ansible-lint:
- **Pre-commit:** Fast syntax validation only (1-3 seconds)
- **CI:** Full ansible-lint with all rules (thorough validation)

**What syntax-check catches:**
- ✅ YAML syntax errors
- ✅ Undefined variables
- ✅ Invalid module names
- ✅ Template syntax errors
- ✅ Basic Ansible structure issues

**What only CI ansible-lint catches:**
- Style issues (naming conventions, formatting)
- Best practices (fqcn, no-changed-when, etc.)
- Deprecated modules
- Security issues

**Performance improvement:**
- **Before:** 15-42s for ansible-lint (inherently slow)
- **After:** 1-3s for syntax-check (only essential validation)
- **Speedup:** ~10-20x faster!

### 2. CI Thorough Validation

Added `.github/workflows/ci.yml` - `ansible-lint-full` job:
- **Full validation** - No NODEPS, validates module parameters
- **All playbooks** - Lints every playbook in `ansible/`
- **Incremental** - Only runs if `ansible/` changed
- **Cached** - Galaxy collections/roles cached between runs

**Why two modes?**
- **Pre-commit (fast):** Catch breaking errors immediately (1-3s)
- **CI (thorough):** Enforce style, best practices, security (42s, but that's normal)

**Benefits:**
- ✅ **Fast feedback loop:** See syntax errors in seconds, not minutes
- ✅ **No false sense of security:** CI still enforces full validation
- ✅ **Better developer experience:** Pre-commit doesn't block you for 42s
- ✅ **CI catches everything:** Style, best practices, security all validated before merge

## Test the Changes

```bash
# Test syntax check on a playbook
cd ansible
ansible-playbook --syntax-check wyrm.yaml
# Should complete in 1-2 seconds

# Test via pre-commit (will run yamllint + syntax-check)
pre-commit run --files ansible/wyrm.yaml
# Should complete in 2-3 seconds

# Full ansible-lint (what CI runs)
ansible-lint --config-file ../.ansible-lint.yaml wyrm.yaml
# Takes ~15-17s (this is normal and expected)
```

## When You Need Full Linting Locally

If you want to run the full ansible-lint validation locally (same as CI):

```bash
cd ansible

# Single playbook (takes ~15-17s)
ansible-lint --config-file ../.ansible-lint.yaml wyrm.yaml

# All playbooks (takes ~42s, same as CI)
ansible-lint --config-file ../.ansible-lint.yaml

# Parallel execution (optional, saves time)
./lint-parallel.sh  # All playbooks in parallel (~15-20s)
```

**Note:** Usually you don't need to run full ansible-lint locally - CI will catch style issues.

## Performance Comparison

| Scenario | Time | What It Validates |
|----------|------|-------------------|
| **Pre-commit syntax-check** | 1-3s | Syntax errors, undefined vars, invalid modules |
| **Full ansible-lint (single)** | ~15s | Everything (style, best practices, security) |
| **Full ansible-lint (all)** | ~42s | Everything on all playbooks |
| **CI ansible-lint** | ~42s | Same as local, but only runs on changes |

## Summary

**Immediate benefits (no extra work):**
- ✅ **~15x faster pre-commit** (42s → 1-3s for syntax check)
- ✅ Syntax errors caught immediately
- ✅ CI still enforces all rules (no loss of coverage)
- ✅ Better developer experience

**When you need it:**
- ✅ Manual full lint available (`ansible-lint` or `./lint-parallel.sh`)
- ✅ Documented what's slow and why (see `SLOWNESS-IS-NORMAL.md`)
- ✅ Upstream patches ready if needed (see `PERFORMANCE-UPSTREAM.md`)

## Files Created/Modified

- ✅ `ansible/run-syntax-check.sh` - Fast syntax check for pre-commit
- ✅ `.pre-commit-config.yaml` - Use syntax-check instead of ansible-lint
- ✅ `ansible/QUICK-WINS.md` - This file (updated strategy)
- ✅ `ansible/SLOWNESS-IS-NORMAL.md` - Why 42s is expected/normal
- ✅ `ansible/PERFORMANCE.md` - Full optimization guide
- ✅ `ansible/PERFORMANCE-UPSTREAM.md` - Upstream patches
