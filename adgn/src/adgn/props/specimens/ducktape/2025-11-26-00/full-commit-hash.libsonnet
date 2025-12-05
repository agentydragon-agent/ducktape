local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Line 751 calls `get_short_commitish(repo)` to obtain a 7-character commit hash prefix
    for the cache key. Using a shortened hash is unnecessary here.

    **Why full hash is better:**
    Cache keys are SHA256-hashed anyway (line 207), so input length doesn't matter for
    readability or performance. Full hash is more precise (eliminates collision risk) and
    removes the need for a dedicated `get_short_commitish()` function (lines 159-161).

    **Fix:** Use `str(repo.head.peel(pygit2.Commit).id)` directly or inline it into the
    `build_cache_key()` call. Delete `get_short_commitish()` if unused elsewhere.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [159, 161],  // get_short_commitish function - may be deletable
      751,  // Should use full commit hash
    ],
  },
)
