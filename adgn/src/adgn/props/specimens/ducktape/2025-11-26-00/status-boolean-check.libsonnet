local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/git_commit_ai/core.py'],
  ],
  rationale=|||
    Line 735 calls `_format_status_porcelain(repo)` just to check if the result is empty.
    This does unnecessary work: `_format_status_porcelain()` (core.py:69-120) builds a full
    porcelain-format status string, but line 735 only needs a boolean: "are there changes?"

    **The issue:** We're formatting a detailed string just to check its emptiness. At this
    call site, we don't care WHAT the changes are, only WHETHER any exist.

    **Fix:** Use `bool(repo.status())` or a `has_uncommitted_changes(repo)` helper instead.
    `repo.status()` returns a dict; empty dict means no changes.

    Other uses of `_format_status_porcelain()` (core.py:134, editor_template.py:30) are
    legitimate - they need the formatted string. This boolean check should not trigger
    expensive formatting.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      735,  // Unnecessary formatting for boolean check
    ],
    'adgn/src/adgn/git_commit_ai/core.py': [
      [69, 120],  // _format_status_porcelain - complex formatting
    ],
  },
)
