local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The code manually maps pygit2 delta status constants to single-letter codes
    (A/M/D/R/T) in two places, but pygit2 provides a built-in method for this:
    `DiffDelta.status_char()`.

    **Current implementation:**
    Manual if/elif chains mapping pygit2.GIT_DELTA_* constants to single letters (A/M/D/R/T)
    appear in both `_format_name_status` (lines 36-54) and `diffstat` (lines 169-186).

    **Problems:**
    1. **Code duplication**: The same status→letter mapping logic appears twice
    2. **Maintenance burden**: Adding support for new status codes (e.g., COPIED='C')
       requires updating multiple locations
    3. **Ignores available library utility**: pygit2 provides `DiffDelta.status_char()`
       which wraps libgit2's `git_diff_status_char()` - the canonical implementation

    **Correct approach:**
    Use `delta.status_char()` to get single-character abbreviations directly. Handle
    renames by checking `d.status == pygit2.GIT_DELTA_RENAMED` for the two-path format.

    **Benefits:**
    1. Single source of truth via libgit2's canonical implementation
    2. Future-proof: New status codes work automatically
    3. Less code: No manual if/elif chains needed
    4. Correct edge cases: Handles UNTRACKED→space automatically

    **Note:** The `STATUS_LETTER_TO_TEXT` dict (lines 67-73) can remain as-is since
    it maps to display text ("new file:", "modified:"), which is presentation-specific.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [36, 54],   // _format_name_status: manual delta status→letter mapping
      [169, 186], // diffstat: duplicate delta status→letter mapping
    ],
    'adgn/src/adgn/mcp/git_ro/formatting.py': [
      [99, 108],  // _status_char: manual delta status→letter mapping (3rd occurrence)
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/core.py'],
    ['adgn/src/adgn/mcp/git_ro/formatting.py'],
  ],
)
