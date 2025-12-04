local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/git_commit_ai/core.py'],
  ],
  rationale=|||
    Line 735 calls `_format_status_porcelain(repo)` just to check if the result is
    empty. This does unnecessary string formatting work.

    **Current usage (cli.py:735):**
    ```python
    status = _format_status_porcelain(repo)
    if not status:
        print("nothing to commit, working tree clean", file=sys.stderr)
    else:
        print('no changes added to commit (use "git add" and/or "git commit -a")', file=sys.stderr)
    ```

    **Problem:** `_format_status_porcelain()` (core.py:69-120) builds a full
    porcelain-format status string with "XY path" lines. At line 735, we only care
    if there are ANY changes, not what they are.

    **Verified solution:**
    `repo.status()` returns a dict. `bool(repo.status())` works correctly:
    - Empty dict (no changes) → False
    - Non-empty dict (has changes) → True

    **Correct approach:**
    ```python
    if not has_uncommitted_changes(repo):
        print("nothing to commit, working tree clean", file=sys.stderr)
    else:
        print('no changes added to commit (use "git add" and/or "git commit -a")', file=sys.stderr)
    ```

    **Other uses of _format_status_porcelain:**
    - core.py:134 - used in prompt context (legitimate - needs formatted string)
    - editor_template.py:30 - used in editor template (legitimate - needs formatted string)

    So the function is still needed, just not for this boolean check.

    **Benefits:**
    1. Faster - no string building for boolean check
    2. Clearer intent - we're checking existence, not formatting
    3. Simpler - one-liner instead of complex formatting logic
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
