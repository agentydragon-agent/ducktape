local I = import '../../specimens/lib.libsonnet';

// iss-002: Manual delta status mapping instead of using pygit2's status_char()

I.issueOneOccurrence(
  rationale= |||
    The code manually maps pygit2 delta status constants to single-letter codes
    (A/M/D/R/T) in two places, but pygit2 provides a built-in method for this:
    `DiffDelta.status_char()`.

    **Current implementation (_format_name_status, lines 36-54):**
    ```python
    for d in diff.deltas:
        st = d.status
        if st == pygit2.GIT_DELTA_ADDED:
            lines.append(f"A\t{d.new_file.path}")
        elif st == pygit2.GIT_DELTA_DELETED:
            lines.append(f"D\t{d.old_file.path}")
        elif st == pygit2.GIT_DELTA_MODIFIED:
            lines.append(f"M\t{d.new_file.path}")
        elif st == pygit2.GIT_DELTA_RENAMED:
            lines.append(f"R\t{d.old_file.path}\t{d.new_file.path}")
        elif st == pygit2.GIT_DELTA_TYPECHANGE:
            lines.append(f"T\t{d.new_file.path}")
        else:
            continue
    ```

    **Current implementation (diffstat, lines 169-186):**
    ```python
    for d in diff.deltas:
        st = d.status
        if st == pygit2.GIT_DELTA_ADDED:
            lines.append(f"{d.new_file.path} | A")
        elif st == pygit2.GIT_DELTA_DELETED:
            lines.append(f"{d.old_file.path} | D")
        # ... similar pattern for M/R/T
    ```

    **Problems:**

    1. **Code duplication**: The same status→letter mapping logic appears twice
    2. **Maintenance burden**: Adding support for new status codes (e.g., COPIED='C')
       requires updating multiple locations
    3. **Ignores available library utility**: pygit2 provides `DiffDelta.status_char()`
       which wraps libgit2's `git_diff_status_char()` - the canonical implementation
       used by git itself

    **The correct approach:**

    Use `delta.status_char()` to get the single-character abbreviation:

    ```python
    def _format_name_status(repo: pygit2.Repository, include_all: bool) -> str:
        diff = _diff(repo, include_all)
        lines: list[str] = []
        for d in diff.deltas:
            status_letter = d.status_char()

            # Skip statuses we don't want (e.g., untracked shows as space)
            if status_letter == ' ':
                continue

            if d.status == pygit2.GIT_DELTA_RENAMED:
                lines.append(f"{status_letter}\t{d.old_file.path}\t{d.new_file.path}")
            else:
                lines.append(f"{status_letter}\t{d.new_file.path}")
        return "\n".join(lines)
    ```

    Similarly for `diffstat()`.

    **Benefits:**

    1. **Single source of truth**: libgit2's canonical implementation handles all cases
    2. **Future-proof**: New status codes added to libgit2 work automatically
    3. **Less code**: No manual if/elif chains needed
    4. **Correct edge cases**: Handles special cases like UNTRACKED→space automatically

    **Note on STATUS_LETTER_TO_TEXT mapping:**

    The `STATUS_LETTER_TO_TEXT` dict (lines 67-73) can remain as-is since it maps
    to human-readable text ("new file:", "modified:") which is display-specific,
    not a library concern. However, the status→letter mapping should use the
    library method.
  |||,
  properties=['avoid-duplication', 'use-platform-primitives'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [36, 54],   // _format_name_status: manual delta status→letter mapping
      [169, 186], // diffstat: duplicate delta status→letter mapping
    ],
    'adgn/src/adgn/mcp/git_ro/formatting.py': [
      [99, 108],  // _status_char: manual delta status→letter mapping (3rd occurrence)
    ],
  },
  gap_note= |||
    This finding illustrates two principles:

    1. **"use-platform-primitives"**: When a library provides a canonical utility
       for a task (especially one that wraps the underlying C library's official
       implementation), prefer it over reimplementing the logic manually. This is
       particularly important for Git operations where libgit2 is the authoritative
       source.

    2. **"avoid-duplication"**: When the same logic appears in multiple places,
       it's a signal that either (a) it should be factored into a shared helper,
       or (b) as in this case, there's likely a platform primitive that handles
       it already.

    The combination of these principles suggests checking library documentation
    before implementing mappings or conversions that seem fundamental to the
    library's domain.
  |||,
)
