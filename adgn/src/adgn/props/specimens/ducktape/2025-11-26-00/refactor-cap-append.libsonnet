local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 18-29 define `_cap_append()` which mutates parts list and handles truncation. Forces callers (lines 133-149) to think about truncation at each append.

    Problems: (1) caller must know when to use `_cap_append()` vs `parts.append()`, (2) truncation interleaved with data collection, (3) same cap/note constants repeated 4 times at call sites, (4) function mutates list and returns boolean, (5) magic constants duplicated instead of centralized.

    Replace with `join_with_truncation(parts, max_chars, note)` that takes complete list and truncates once at end. Callers build full list using plain `append()`, then call `join_with_truncation()` once. Define constants at module level, not repeated at call sites. Benefits: separation of concerns, pure function, constants defined once, easy to change behavior in one place.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [18, 29],  // _cap_append - poor abstraction
      [133, 149],  // Caller that interleaves truncation with data collection
    ],
  },
)
