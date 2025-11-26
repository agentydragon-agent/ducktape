local I = import '../../specimens/lib.libsonnet';

// iss-028: Inline single-use variable 'raw'

I.issueOneOccurrence(
  rationale=|||
    Line 154 creates `raw`, which is immediately passed to `_truncate_hunks()` on line 156.
    Single-use variable should be inlined.

    **Current:** `raw = ... ; return _truncate_hunks(raw)`
    **Fix:** `return _truncate_hunks(... if previous_message else ...)`
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [154, 156],  // raw should be inlined
    ],
  },
)
