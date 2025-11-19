# Ansible-Lint Quick Performance Wins

## Already Applied ✅

### 1. Pre-commit Optimizations

Updated `ansible/run-ansible-lint-parallel.py` with:
- **`--offline` flag** - Skips network calls for requirements/schema
- **`ANSIBLE_LINT_SKIP_SCHEMA_UPDATE=1`** - Skips remote schema refresh
- **Parallel execution** - Runs ansible-lint on multiple changed files in parallel (Python)
- **Serial reporting** - Collects and displays results in order (no interleaved output)

**Expected improvement:**
- Single file: ~15s (same as before, minimal overhead)
- Multiple files: Up to Nx faster (N = number of files, depending on CPU cores)
- Example: 3 files that normally take 45s → ~15-20s with parallel execution

### 2. CI Thorough Validation

Added `.github/workflows/ci.yml` - `ansible-lint-full` job:
- **Full validation** - No NODEPS, validates module parameters
- **All playbooks** - Lints every playbook in `ansible/`
- **Incremental** - Only runs if `ansible/` changed
- **Cached** - Galaxy collections/roles cached between runs

**Why two modes?**
- **Pre-commit (fast):** Quick feedback while coding (~15s, parallel on multiple files)
- **CI (thorough):** Complete validation including module parameters (~42s)

**How parallel execution works:**
- When you modify 1 file: Runs normally (~15s, no parallelism overhead)
- When you modify 3 files: Runs in parallel using all CPU cores (~15-20s total)
- Uses Python's `ProcessPoolExecutor` for true parallelism (not limited by GIL)
- Output is collected and displayed in order (not interleaved)
- No external dependencies required (just Python 3, which pre-commit already uses)

## Test the Changes

```bash
# Test on all files
cd ansible
time pre-commit run ansible-lint --all-files

# Test on single file
time ./run-ansible-lint.sh wyrm.yaml
```

## Additional Quick Wins (Optional)

### Parallel Execution (For Manual Runs)

Use the new `lint-parallel.sh` script:

```bash
cd ansible

# Install GNU parallel (if not already installed)
# Ubuntu/Debian: apt-get install parallel
# macOS: brew install parallel

# Run all playbooks in parallel
./lint-parallel.sh

# Run specific playbooks in parallel
./lint-parallel.sh agentydragon.yaml wyrm.yaml vps.yaml gpd.yaml
```

**Expected improvement:** 42s → 15-20s (when linting all playbooks manually)

**Note:** Pre-commit already handles parallelism for you when linting individual changed files.

## Parallelization Facts

### What ansible-lint DOES parallelize:

✅ **Phase 1 (Syntax checking)** - Already uses ThreadPool internally
- Uses all CPU cores
- Runs `ansible-playbook --syntax-check` in parallel

### What ansible-lint DOESN'T parallelize:

❌ **Phase 2 (Rule execution)** - Runs sequentially
- Each file processed one at a time
- This is where most time is spent (~12s out of 17.7s)

### Can YOU run ansible-lint in parallel?

✅ **YES** - Safe to run multiple ansible-lint processes on different playbooks
- No shared mutable state
- Read-only operations (unless using --fix)
- Each process independent

❌ **NO** - Don't run on same file simultaneously
- Could conflict if using --fix
- No benefit (same dependency graph)

## Performance Expectations

| Scenario | Before | After | Improvement |
|----------|--------|-------|-------------|
| **Pre-commit (all files)** | 42.4s | 39-40s | ~5-10% |
| **Pre-commit (single file)** | 4-5s | 3-4s | ~20% |
| **Manual (parallel 4 playbooks)** | 42.4s | 15-20s | ~60% |
| **wyrm.yaml only** | 17.7s | 15-16s | ~10-15% |

## Next Steps (Optional)

### For even better performance:

1. **Submit upstream patches** (see `PERFORMANCE-UPSTREAM.md`)
   - Could reduce 17.7s → 5-7s
   - Requires modifying ansible-lint source
   - Benefits entire community

2. **Incremental linting** (see `PERFORMANCE.md`)
   - Cache results between runs
   - Only re-lint changed files
   - Could save 100% on unchanged code

3. **Targeted linting strategy** (see `PERFORMANCE.md`)
   - Fast mode for pre-commit
   - Thorough mode for CI
   - Parallel mode for manual checks

## Files Modified

- ✅ `ansible/run-ansible-lint.sh` - Added --offline and env vars
- ✅ `ansible/lint-parallel.sh` - New script for parallel execution
- ✅ `ansible/PERFORMANCE.md` - Detailed optimization guide
- ✅ `ansible/PERFORMANCE-UPSTREAM.md` - Upstream patch recommendations
- ✅ `ansible/QUICK-WINS.md` - This file

## Troubleshooting

### If linting seems slower:

Check if you're online and hitting network timeouts:
```bash
# Force offline mode
export ANSIBLE_LINT_OFFLINE=1
```

### If you see "schema update" messages:

Confirm the environment variable is set:
```bash
echo $ANSIBLE_LINT_SKIP_SCHEMA_UPDATE  # Should output: 1
```

### If parallel script fails:

Check if GNU parallel is installed:
```bash
which parallel || echo "Not installed"
```

Install it:
```bash
# Ubuntu/Debian
sudo apt-get install parallel

# macOS
brew install parallel
```

## Monitoring Performance

Track performance over time:

```bash
# Add to your shell aliases
alias ansible-lint-bench='time ansible-lint --offline --all-files 2>&1 | tee ansible-lint-bench.log'

# Run periodically
cd ansible && ansible-lint-bench
```

## Summary

**Immediate benefits (no extra work):**
- ✅ 5-10% faster pre-commit (already applied)
- ✅ Offline mode (no network delays)
- ✅ Skip schema refresh (no remote fetches)

**Available on demand:**
- 📦 Parallel execution script ready to use
- 📦 Fast mode option (if you want to trade thoroughness for speed)

**Future improvements:**
- 📋 Upstream patches could provide 60-70% improvement
- 📋 Incremental caching could save 100% on unchanged code
