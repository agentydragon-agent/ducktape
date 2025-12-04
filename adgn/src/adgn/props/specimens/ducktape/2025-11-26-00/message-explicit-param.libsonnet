local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The function `_execute_git_commit()` (lines 571-584) takes `message_args: list[str]`
    which is always `["-m", msg]` or `["-F", path, "--cleanup=strip"]`.

    **Current callers:**
    - Line 591: `_execute_git_commit(["-m", msg], passthru)`
    - Line 647: `_execute_git_commit(["-F", str(commit_msg_path), "--cleanup=strip"], passthru)`

    **Problem:** If all callers pass `-m msg`, the message should be an explicit
    parameter. Splitting into separate list arguments obscures the API.

    **Verified:** Line 647 is the ONLY caller that uses `-F` flag. Line 591 uses `-m` flag.
    The function accepts `message_args` but only two callers exist, each using different format.
    If yes, consider making `message: str` a required parameter and handling `-F`
    vs `-m` internally, or making two separate functions.

    **Proposed signature:**
    ```python
    async def _execute_git_commit(message: str, passthru: list[str]) -> None:
        """Execute git commit with message."""
        # Validate message is non-empty (see issue 035)
        commit_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message, "--no-verify", *passthru
        )
        ...
    ```

    Or keep `-F` path separate if needed for editor flow.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [571, 584],  // _execute_git_commit with message_args list
      591,  // Caller with -m
      647,  // Caller with -F
    ],
  },
)
