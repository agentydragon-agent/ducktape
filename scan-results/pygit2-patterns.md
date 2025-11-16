# Scan Results: pygit2 Type Narrowing Patterns

## Summary

This scan searched for pygit2 type narrowing patterns across the ducktape codebase, focusing on:
1. `isinstance` checks with `pygit2.Tag` or `pygit2.Commit`
2. Potentially unnecessary `peel(pygit2.Commit)` calls

**Findings**: Found 1 exemplary pattern implementation and 5 instances where type narrowing could potentially be improved or simplified.

## Instances Found

### 1. Exemplary Pattern (Best Practice) ✓

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/git_ro/server.py`
**Lines**: 388-395

```python
obj_any = repo.revparse_single(objspec)
# Narrow runtime types explicitly
if isinstance(obj_any, pygit2.Tag):
    obj = obj_any.peel(pygit2.Commit)
elif isinstance(obj_any, pygit2.Commit):
    obj = obj_any
else:
    raise TypeError(f"Unexpected git object type for {objspec}: {type(obj_any)!r}")
```

**Why it matches**: This is the exact pattern described in the scan prompt - proper type narrowing using isinstance checks. It correctly handles Tags by peeling to Commit, recognizes when an object is already a Commit (avoiding unnecessary peel), and raises a clear error for unexpected types. This is the canonical example.

---

### 2. One-liner isinstance with peel (Tree)

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/git_ro/server.py`
**Line**: 373

```python
tree = root_obj.tree if isinstance(root_obj, pygit2.Commit) else root_obj.peel(pygit2.Tree)
```

**Why it matches**: Uses isinstance to check for Commit type, but in a ternary expression. If it's a Commit, uses the `.tree` property; otherwise peels to Tree. This is a compact pattern for handling Commit vs other object types when getting a tree.

---

### 3. Unconditional peel (same file, later)

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/git_ro/server.py`
**Line**: 399

```python
if obj.parent_ids:
    parent = repo[obj.parent_ids[0]].peel(pygit2.Commit)
```

**Why it matches**: Calls `peel(pygit2.Commit)` without prior isinstance check. This occurs right after the exemplary pattern (lines 390-395), where `obj` is known to be a Commit. Looking up a parent by ID should return a Commit, but type narrowing here could make this more explicit.

---

### 4. Branch creation - target peel

**File**: `/home/user/ducktape/wt/src/wt/server/git_manager.py`
**Lines**: 69-70

```python
target_obj = self._main_repo.revparse_single(source_branch)
target_commit = target_obj.peel(pygit2.Commit)
```

**Why it matches**: Unconditionally peels to Commit without checking if the object is already a Commit. Since `source_branch` is typically "HEAD" or a branch name, this will usually be a Commit already. Per the scan prompt guidance, if the object is already a Commit, `peel(pygit2.Commit)` is a no-op identity operation that could be avoided with type narrowing.

---

### 5. Worktree branch creation - target peel

**File**: `/home/user/ducktape/wt/src/wt/server/git_manager.py`
**Lines**: 171-172

```python
target_obj = self._main_repo.revparse_single(self.config.upstream_branch)
target = target_obj.peel(pygit2.Commit)
```

**Why it matches**: Similar to #4 - unconditionally peels to Commit when creating a branch. The upstream branch reference would typically resolve to a Commit, making the peel potentially unnecessary if type narrowing were used.

---

### 6. Git commit AI - HEAD operations

**File**: `/home/user/ducktape/adgn/src/adgn/git_commit_ai/cli.py`
**Lines**: 132, 134, 166

```python
# Line 132
head = repo.revparse_single("HEAD").peel(pygit2.Commit)

# Line 134
parent = repo.revparse_single("HEAD^").peel(pygit2.Commit)

# Line 166
commit = repo.revparse_single("HEAD").peel(pygit2.Commit)
```

**Why it matches**: Three instances of unconditional `peel(pygit2.Commit)` on HEAD/parent references. HEAD almost always points to a Commit (except in detached HEAD pointing to a tag), so these peels are likely no-ops in the common case. Type narrowing with isinstance would make the code more explicit and avoid unnecessary peeling.

## Improvement Opportunities

The scan prompt notes that:
- `commit.peel(pygit2.Commit)` is identity (noop) if you already have a Commit
- With `types-pygit2>=1.15.0` installed, proper type stubs provide return types that work well with isinstance narrowing

### Potential improvements:

1. **For HEAD/branch references** (instances #4, #5, #6): These typically resolve directly to Commits. Adding isinstance checks would:
   - Make the code more explicit about type expectations
   - Avoid no-op peel calls in the common case
   - Provide better error messages when unexpected types are encountered

2. **For parent lookups** (instance #3): Could benefit from explicit type narrowing similar to the exemplary pattern, especially since the context guarantees it's working with commits.

### Impact Assessment:

- **Performance**: Minimal - peel is already a no-op for same-type operations
- **Type Safety**: Improved - makes type flow more explicit for type checkers
- **Maintainability**: Better - clearer intent and better error messages
- **Correctness**: No change - current code works correctly

## Recommendations

1. Install `types-pygit2>=1.15.0` if not already present for better type hints
2. Consider applying the exemplary pattern (lines 390-395) to instances #4, #5, and #6 where branch/HEAD refs are being resolved
3. Instance #3 could remain as-is since it's in a context where types are already narrowed, but adding an isinstance assertion could improve clarity
4. Instance #2 (line 373) is already well-optimized for its use case

## Files Scanned

The scan covered 20 Python files that import pygit2:
- `wt/src/wt/client/wt_client.py`
- `wt/src/wt/server/git_manager.py`
- `wt/src/wt/server/pr_service.py`
- `wt/src/wt/server/repo_status.py`
- `wt/src/wt/server/services.py`
- `wt/src/wt/server/worktree_service.py`
- `wt/tests/` (various test files)
- `adgn/src/adgn/git_commit_ai/` (CLI and core files)
- `adgn/src/adgn/mcp/git_ro/` (server and formatting)
- `adgn/tests/llm/git_repo_utils.py`
