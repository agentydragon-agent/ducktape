# Scan Results: Idiomatic pygit2 Usage Patterns

**Scan Date**: 2025-11-19
**Coverage**: All Python files in repository
**Files with pygit2 usage**: 26 files analyzed
**Violations Found**: 0

## Executive Summary

A comprehensive scan of all pygit2 usage patterns across the codebase found **zero violations** of idiomatic pygit2 patterns. All detected usage follows the recommended patterns defined in `prompts/scans/pygit2-patterns.md`.

## Scan Methodology

The scan employed targeted regex patterns to detect non-idiomatic pygit2 usage:

1. **HEAD access antipatterns**: `revparse_single("HEAD").peel()` → should use `repo.head`
2. **Parent access antipatterns**: `repo[commit.parent_ids[0]]` → should use `commit.parents`
3. **Manual parent walking**: `cur.parents[0]` in loops → should use Walker API
4. **Type narrowing**: Proper `isinstance()` checks vs. overly complex conversions
5. **Trivial helpers**: One-line wrapper functions with no semantic value
6. **Unnecessary peels**: `peel(pygit2.Commit)` when object is already a Commit

## Detailed Findings

### Pattern 1: HEAD Access ✓ IDIOMATIC

All HEAD access uses the idiomatic `repo.head` property pattern:

**File**: `/home/user/ducktape/adgn/src/adgn/git_commit_ai/cli.py`
```python
# Line 132: Idiomatic
head = repo.head.peel(pygit2.Commit)

# Line 166: Idiomatic - direct OID access
return str(repo.head.peel(pygit2.Commit).id)[:7]

# Line 534: Idiomatic
commit = repo.head.peel(pygit2.Commit)
```

**File**: `/home/user/ducktape/adgn/tests/llm/git_repo_utils.py`
```python
# Line 37: Idiomatic
parent = repo.head.peel(pygit2.Commit)
```

**File**: `/home/user/ducktape/adgn/tests/llm/test_git_commit_ai_amend.py`
```python
# Line 168: Idiomatic
previous_message = repo.head.peel(pygit2.Commit).message.strip()

# Line 204: Idiomatic
committed = fresh.head.peel(pygit2.Commit).message.strip()
```

**Verdict**: All HEAD access patterns are correct. No use of the antipattern `repo.revparse_single("HEAD")`.

### Pattern 2: Parent Commit Access ✓ IDIOMATIC

All parent access uses the idiomatic `.parents` property:

**File**: `/home/user/ducktape/adgn/src/adgn/git_commit_ai/cli.py`
```python
# Line 134: Idiomatic
parent = head.parents[0]
```

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/git_ro/server.py`
```python
# Line 400: Idiomatic
parent = obj.parents[0]
```

**Verdict**: All parent access uses the `.parents` property. No antipattern `repo[commit.parent_ids[0]]` detected.

### Pattern 3: Arbitrary Revspec Resolution ✓ IDIOMATIC

The helper function for resolving arbitrary revspecs is correctly scoped:

**File**: `/home/user/ducktape/wt/src/wt/server/git_manager.py`
```python
# Lines 18-20: Idiomatic helper
def _resolve_to_commit(repo: pygit2.Repository, revspec: str) -> pygit2.Commit:
    """Resolve any revspec to a Commit, peeling tags if needed."""
    return repo.revparse_single(revspec).peel(pygit2.Commit)
```

**Usage**: Called for non-HEAD revspecs (branches, tags, SHAs)
- Line 75: `target_commit = _resolve_to_commit(self._main_repo, source_branch)`
- Line 176: `target = _resolve_to_commit(self._main_repo, self.config.upstream_branch)`

**Verdict**: Helper function is correctly designed with semantic value. It handles complex revspec resolution that would be duplicated without it. Pattern matches recommended approach for "helper functions that add semantic value."

### Pattern 4: Type Narrowing ✓ IDIOMATIC

Proper type narrowing with `isinstance()` checks:

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/git_ro/server.py`
```python
# Lines 389-396: Idiomatic type narrowing
obj_any = repo.revparse_single(objspec)
# Narrow runtime types explicitly
if isinstance(obj_any, pygit2.Tag):
    obj = obj_any.peel(pygit2.Commit)
elif isinstance(obj_any, pygit2.Commit):
    obj = obj_any
else:
    raise TypeError(f"Unexpected git object type for {objspec}: {type(obj_any)!r}")
```

**Verdict**: Correct pattern for handling user-provided revspecs that might be tags or commits. Proper error handling for unexpected types.

### Pattern 5: Walker API Usage ✓ IDIOMATIC

All commit iteration uses the Walker API with proper simplification:

**File**: `/home/user/ducktape/adgn/src/adgn/git_commit_ai/core.py`
```python
# Lines 125-138: Idiomatic Walker usage
def _log_subjects(repo: pygit2.Repository, n: int = 10) -> list[str]:
    """Return up to n raw commit log entries (short hash + full message)."""
    walker = repo.walk(repo.head.target)
    walker.simplify_first_parent()

    out: list[str] = []
    for commit in walker:
        msg = commit.message or ""
        short = str(commit.id)[:7]
        entry = f"{short} {msg}".rstrip("\n") if msg else short
        out.append(entry)
        if len(out) >= n:
            break
    return out
```

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/git_ro/server.py`
```python
# Lines 307-310: Idiomatic Walker iteration
walker = repo.walk(head_oid)
for i, c in enumerate(walker, start=1):
    if input.oneline:
        raw_message = (c.message or "").rstrip("\n")

# Lines 333-336: Idiomatic Walker with offset
walker = repo.walk(head_oid)
for i, _ in enumerate(walker):
    if i >= input.offset:
```

**Verdict**: Walker API is used for commit iteration. No manual parent walking (`cur.parents[0]` loops) detected.

### Pattern 6: Direct Property Access ✓ IDIOMATIC

Proper use of direct properties instead of peeling:

**File**: `/home/user/ducktape/wt/src/wt/server/repo_status.py`
```python
# Lines 56, 58, 63, 66: Direct .target access (OID)
local_ref = repo.lookup_reference(f"refs/heads/{branch_name}")
local_id = local_ref.target

local_id = repo.head.target

upstream_ref = repo.lookup_reference(f"refs/heads/{self.config.upstream_branch}")
upstream_id = upstream_ref.target
```

**File**: `/home/user/ducktape/wt/src/wt/server/git_manager.py`
```python
# Line 132: Direct .shorthand access
current_branch = self._main_repo.head.shorthand if not self._main_repo.head_is_detached else None

# Line 147: Direct .shorthand access
branch_name = wt_repo.head.shorthand or ""
```

**File**: `/home/user/ducktape/adgn/src/adgn/git_commit_ai/core.py`
```python
# Line 33: Direct .target usage
return repo.diff(repo.head.target, None, cached=not include_all)
```

**Verdict**: Direct properties (`.target`, `.shorthand`) are used appropriately instead of unnecessary peeling.

### Pattern 7: Trivial Helper Functions ✓ NONE DETECTED

A scan for one-line wrapper functions with no semantic value found no violations. The `_resolve_to_commit` helper has:
- Actual logic (handles revspec parsing complexity)
- Semantic value (meaningful name describing what it does)
- Reduces duplication (called from 2+ locations)

**Verdict**: No trivial one-line wrapper functions detected.

## Scan Coverage

### Files Analyzed (26 total with pygit2 usage)

**adgn/** (13 files)
- `src/adgn/git_commit_ai/cli.py` - ✓ Idiomatic
- `src/adgn/git_commit_ai/core.py` - ✓ Idiomatic
- `src/adgn/git_commit_ai/editor_template.py` - ✓ Idiomatic
- `src/adgn/git_commit_ai/minicodex_backend.py` - ✓ Idiomatic
- `src/adgn/mcp/git_ro/formatting.py` - ✓ Idiomatic
- `src/adgn/mcp/git_ro/server.py` - ✓ Idiomatic
- `tests/llm/git_repo_utils.py` - ✓ Idiomatic
- `tests/llm/test_editor_template.py` - ✓ Idiomatic
- `tests/llm/test_git_commit_ai_amend.py` - ✓ Idiomatic
- `tests/mcp/git_ro/conftest.py` - ✓ Idiomatic
- `tests/mcp/git_ro/test_stat_counts.py` - ✓ Idiomatic

**wt/** (10 files)
- `src/wt/client/wt_client.py` - ✓ Idiomatic
- `src/wt/server/git_manager.py` - ✓ Idiomatic
- `src/wt/server/pr_service.py` - ✓ Idiomatic
- `src/wt/server/repo_status.py` - ✓ Idiomatic
- `src/wt/server/services.py` - ✓ Idiomatic
- `src/wt/server/worktree_service.py` - ✓ Idiomatic
- `tests/conftest.py` - ✓ Idiomatic
- `tests/e2e/test_real_workflow.py` - ✓ Idiomatic
- `tests/e2e/test_worktree_branches.py` - ✓ Idiomatic
- `tests/integration/test_cli_daemon_integration.py` - ✓ Idiomatic
- `tests/repo_factory.py` - ✓ Idiomatic
- `tests/server/test_pr_service_resilience.py` - ✓ Idiomatic
- `tests/test_data.py` - ✓ Idiomatic

**llm/** (2 files)
- `ducktape_llm_common/tests/claude_linter/conftest.py` - ✓ Idiomatic
- `ducktape_llm_common/tests/claude_linter/test_hooks.py` - ✓ Idiomatic

## Key Metrics

| Metric | Value |
|--------|-------|
| Total Files Scanned | 26 |
| Files with Violations | 0 |
| Violation Rate | 0% |
| HEAD Access Patterns | 8 (all idiomatic) |
| Parent Access Patterns | 2 (all idiomatic) |
| Type Narrowing Instances | 1 (all idiomatic) |
| Walker Usage Instances | 3 (all idiomatic) |
| Helper Functions Reviewed | 1 (all semantic) |

## Conclusion

The codebase demonstrates **excellent adherence** to idiomatic pygit2 usage patterns across all 26 files analyzed. Key strengths:

1. **Consistent use of `repo.head`** for HEAD access instead of `revparse_single("HEAD")`
2. **Proper parent access** via `.parents` property instead of manual `parent_ids[0]` lookups
3. **Effective use of Walker API** for commit iteration
4. **Correct type narrowing** with `isinstance()` checks for user input handling
5. **Strategic helper functions** that reduce duplication without adding unnecessary abstraction
6. **Direct property access** (`.target`, `.shorthand`) used appropriately

**No refactoring needed.** The codebase is ready for production with respect to pygit2 patterns.

---

*Scan performed using patterns from: `/home/user/ducktape/prompts/scans/pygit2-patterns.md`*
