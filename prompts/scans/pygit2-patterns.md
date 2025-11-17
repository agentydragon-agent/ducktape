# Scan: Idiomatic pygit2 Usage Patterns

## Context
@../shared-context.md

## Idiomatic Patterns

### 1. Getting HEAD OID or Commit

**Direct OID access** (when you only need the OID):
```python
# BAD: Overcomplicated - peeling just to get ID
oid = repo.revparse_single("HEAD").peel(pygit2.Commit).id

# GOOD: Direct property access
oid = repo.head.target
```

**Commit access** (when you need the commit object):
```python
# BAD: Using revparse_single
head = repo.revparse_single("HEAD").peel(pygit2.Commit)

# GOOD: Using repo.head property
head = repo.head.peel(pygit2.Commit)

# ALSO GOOD: peel() without argument (defaults to underlying object)
head = repo.head.peel()
```

The `repo.head` property returns a Reference. Use `.target` for direct OID access, `.peel()` for commit object.

### 2. Getting Parent Commits

**BAD** (unnecessarily complex):
```python
parent = repo[commit.parent_ids[0]].peel(pygit2.Commit)
```

**GOOD** (idiomatic):
```python
parent = commit.parents[0]
```

The `.parents` property already returns a `list[Commit]`, no peeling needed.

### 3. Resolving Arbitrary Revspecs

For branch names, tags, or other revspecs:

**Pattern: Create a helper function**:
```python
def _resolve_to_commit(repo: pygit2.Repository, revspec: str) -> pygit2.Commit:
    """Resolve any revspec to a Commit, peeling tags if needed."""
    if revspec == "HEAD":
        return repo.head.peel(pygit2.Commit)
    return repo.revparse_single(revspec).peel(pygit2.Commit)
```

This handles HEAD idiomatically while using `revparse_single().peel()` for other revspecs.

### 4. Type Narrowing for User-Provided Revspecs

When accepting revspecs from users that might be tags or commits:

```python
obj = repo.revparse_single(user_revspec)
if isinstance(obj, pygit2.Tag):
    commit = obj.peel(pygit2.Commit)
elif isinstance(obj, pygit2.Commit):
    commit = obj
else:
    raise TypeError(f"Expected commit or tag, got {type(obj)!r}")
```

**Why**: This pattern makes the tag-to-commit conversion explicit and handles unexpected types gracefully.

**Note**: `commit.peel(pygit2.Commit)` is a no-op - if you know it's already a Commit, don't peel.

### 5. Commit Iteration - Use Walker

**BAD** (manual parent walking):
```python
def get_recent_commits(repo: pygit2.Repository, n: int) -> list[pygit2.Commit]:
    commits = []
    cur = repo.head.peel(pygit2.Commit)
    for i in range(n):
        commits.append(cur)
        if not cur.parents:
            break
        cur = cur.parents[0]  # Manual first-parent walking
    return commits
```

**GOOD** (using Walker):
```python
def get_recent_commits(repo: pygit2.Repository, n: int) -> list[pygit2.Commit]:
    walker = repo.walk(repo.head.target)
    walker.simplify_first_parent()

    commits = []
    for commit in walker:
        commits.append(commit)
        if len(commits) >= n:
            break
    return commits
```

**Why Walker is better**:
- Native first-parent traversal with `simplify_first_parent()`
- Iterator-based (Pythonic)
- No manual parent checking or index tracking
- Standard pygit2 pattern for commit history

### 6. Avoid Trivial Helper Functions

Don't create one-line wrappers around pygit2 operations unless they add semantic value.

**BAD** (pointless abstraction):
```python
def _head_commit_oid(repo: pygit2.Repository) -> pygit2.Oid:
    return repo.head.peel(pygit2.Commit).id

def _index_tree_oid(repo: pygit2.Repository) -> pygit2.Oid:
    return repo.index.write_tree()

# Usage scattered throughout code
oid = _head_commit_oid(repo)
tree = _index_tree_oid(repo)
```

**GOOD** (direct usage):
```python
# Just use the idiomatic pattern directly
oid = repo.head.target  # Even better: direct OID access
tree = repo.index.write_tree()
```

**When helpers ARE good**:
```python
# GOOD: Adds semantic value and handles multiple cases
def _resolve_to_commit(repo: pygit2.Repository, revspec: str) -> pygit2.Commit:
    """Resolve any revspec to a Commit, handling HEAD idiomatically."""
    if revspec == "HEAD":
        return repo.head.peel(pygit2.Commit)
    return repo.revparse_single(revspec).peel(pygit2.Commit)

# GOOD: Encapsulates complex logic with meaningful name
def _is_ancestor_of(repo: pygit2.Repository, ancestor: pygit2.Oid, descendant: pygit2.Oid) -> bool:
    """Check if ancestor is reachable from descendant."""
    return repo.descendant_of(descendant, ancestor)
```

**Rule**: If the helper function body is just a single library call with no logic, it's probably unnecessary. Use the library directly.

## Quick API Reference

These are the idiomatic pygit2 APIs you should use by default:

### Repository Operations
```python
repo.head                           # Reference - the current HEAD reference
repo.head.target                    # Oid - OID that HEAD points to (no peeling needed)
repo.head.peel()                    # Object - peel to underlying object (usually Commit)
repo.head.peel(pygit2.Commit)      # Commit - explicitly peel to Commit type
repo.head.shorthand                 # str - branch name (e.g., "main") or None if detached
repo.head_is_detached               # bool - whether HEAD is detached

repo.walk(oid)                      # Walker - create commit walker starting from oid
repo.revparse_single(revspec)       # Object - resolve revspec (use for non-HEAD refs)
repo.index.write_tree()             # Oid - write index to tree object
repo.diff(a, b, cached=True)        # Diff - compare commits/trees
repo.status()                       # dict[str, int] - working directory status
```

### Commit Operations
```python
commit.parents                      # list[Commit] - parent commits (no peeling needed)
commit.parent_ids                   # list[Oid] - parent OIDs (prefer .parents for commit objects)
commit.message                      # str - full commit message
commit.id                           # Oid - commit SHA
commit.tree                         # Tree - tree object for this commit
```

### Walker Operations
```python
walker = repo.walk(oid)             # Create walker
walker.simplify_first_parent()      # Follow only first-parent chain (linear history)
walker.sort(pygit2.GIT_SORT_TIME)  # Sort by time (optional)

for commit in walker:               # Iterator over commits
    process(commit)
```

### Reference Operations
```python
ref.target                          # Oid - OID the reference points to
ref.peel()                          # Object - peel to underlying object
ref.peel(pygit2.Commit)            # Commit - explicitly peel to Commit type
ref.shorthand                       # str - short reference name
```

## Detection Strategy

**Primary Method**: Manual code reading to identify non-idiomatic pygit2 patterns.

**Why automation is insufficient**:
- Determining if code is "non-idiomatic" requires understanding pygit2 API capabilities
- Some patterns exist for good reasons (handling older pygit2 versions, specific edge cases)
- Need to verify refactored code actually works with Walker API, etc.

**Discovery aids** (candidates for manual review):

```bash
# Find HEAD access that could use repo.head.target
rg --type py 'revparse_single\("HEAD"\)\.peel.*\.id'

# Find HEAD access that could use repo.head
rg --type py 'revparse_single\("HEAD"\)\.peel'

# Find parent access that could use commit.parents
rg --type py 'repo\[.*parent_ids\[0\]\]\.peel'

# Find manual parent walking that could use Walker
rg --type py "cur\.parents\[0\]" -B3 -A3

# Find potentially unnecessary peels (for manual review)
rg --type py "peel\(pygit2\.Commit\)" -B2

# Find trivial helper candidates (one-line functions)
rg --type py -A1 '^def _.*\(.*pygit2\.Repository.*\):$' | grep -B1 'return repo\.'
```

## With types-pygit2 Installed

Type stubs (`types-pygit2>=1.15.0`) provide proper return types:
- `repo.head` returns `Reference`
- `Reference.peel(T)` returns `T`
- `commit.parents` returns `list[Commit]`
- `repo.index.write_tree()` returns `Oid`
- No casts needed with isinstance narrowing

## Key Principles

1. **Use direct properties** (`repo.head.target` for OID, `commit.parents` for parent list)
2. **Use Walker for iteration** (instead of manual parent walking)
3. **Peel only when needed** (converting tags, or when you need commit object not OID)
4. **Type narrow explicitly** (isinstance checks for user input)
5. **Create meaningful helpers** (wrap complex patterns, not single calls)
6. **Avoid trivial wrappers** (one-line helpers with no logic are noise)

## References

- [pygit2 Documentation](https://www.pygit2.org/)
- [pygit2 GitHub Repository](https://github.com/libgit2/pygit2)
- Install: `pip install types-pygit2`
