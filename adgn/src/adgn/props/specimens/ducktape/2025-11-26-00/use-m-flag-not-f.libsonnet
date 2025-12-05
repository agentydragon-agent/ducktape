local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 641-647 extract the commit message from the editor file (removing scissors
    and comments), then pass the file path to `git commit -F ... --cleanup=strip`.

    **Problem:** We already did the cleanup ourselves in `_extract_commit_content()`.
    There's no need to use `-F` (read from file) when we have the clean message in
    `commit_message` variable.

    **Current:**
    ```python
    commit_message = _extract_commit_content(final_content)
    if not commit_message:
        print("Aborting commit due to empty commit message.", file=sys.stderr)
        raise ExitWithCode(1)
    await _execute_git_commit(["-F", str(commit_msg_path), "--cleanup=strip"], passthru)
    ```

    **Simplified:**
    ```python
    commit_message = _extract_commit_content(final_content)
    # Empty check removed - see issue 035 (let Git handle it)
    await _execute_git_commit(message=commit_message, passthru=passthru)
    ```

    **Benefits:**
    1. No need to pass file path and `--cleanup=strip` flag
    2. Enables making `message` an explicit parameter (issue 034)
    3. Clearer: we have the message, just use it directly
    4. Don't need to rely on COMMIT_EDITMSG file still existing

    **Note:** This change pairs well with issue 034 (making message an explicit
    required string parameter in `_execute_git_commit`).
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [641, 647],  // Should use -m with extracted message, not -F with file
    ],
  },
)
