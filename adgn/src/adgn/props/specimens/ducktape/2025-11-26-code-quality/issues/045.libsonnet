local I = import '../../specimens/lib.libsonnet';

// iss-045: Inline single-use variable 'status'

I.issueOneOccurrence(
  rationale=|||
    Line 735 creates `status` variable which is immediately used in the if-check on
    line 736. Single-use variable should be inlined.

    **Current:**
    ```python
    status = _format_status_porcelain(repo)
    if not status:
        ...
    ```

    **Fix:**
    ```python
    if not _format_status_porcelain(repo):
        ...
    ```

    **Note:** This issue pairs with issue 046 which questions whether we need to format
    status at all just to check if it's empty.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [735, 736],  // status should be inlined
    ],
  },
)
