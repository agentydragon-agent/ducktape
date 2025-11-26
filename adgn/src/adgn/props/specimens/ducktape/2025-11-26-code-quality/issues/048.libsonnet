local I = import '../../specimens/lib.libsonnet';

// iss-048: Use full commit hash instead of short commitish for cache key

I.issueOneOccurrence(
  rationale=|||
    Line 751 calls `get_short_commitish(repo)` to get a 7-character commit hash prefix
    for the cache key. There's no reason to use a shortened version.

    **Current:**
    ```python
    commitish = get_short_commitish(repo)  # Returns 7-char prefix
    key = build_cache_key(..., commitish=commitish, ...)
    ```

    **Why short commitish is unnecessary:**
    1. Cache key is hashed anyway (build_cache_key uses SHA256, line 207)
    2. Full hash is more precise (no collision risk, however tiny)
    3. Using full hash eliminates the `get_short_commitish()` function call

    **Investigation:** Check if there's a reason for the short version:
    - Human readability? No - cache keys are hashed and stored as filenames
    - Performance? No - the cache key is hashed, so 7 chars vs 40 chars is negligible
    - Compatibility? Check if existing cache needs to be preserved

    **If no reason for short version:**
    ```python
    commitish = str(repo.head.peel(pygit2.Commit).id)
    key = build_cache_key(..., commitish=commitish, ...)
    ```

    Or inline entirely:
    ```python
    key = build_cache_key(
        ...,
        commitish=str(repo.head.peel(pygit2.Commit).id),
        ...
    )
    ```

    **Then delete `get_short_commitish()` function** (lines 159-161) if unused elsewhere.

    **Benefits:**
    1. Simpler - no need for dedicated function
    2. More precise - full hash instead of prefix
    3. Fewer functions to maintain
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [159, 161],  // get_short_commitish function - may be deletable
      751,  // Should use full commit hash
    ],
  },
)
