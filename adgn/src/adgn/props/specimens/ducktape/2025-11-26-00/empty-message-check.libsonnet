local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 588-590 check if the AI message is empty and abort with a custom error.
    This duplicates Git's built-in behavior - Git already rejects empty commit messages.

    **Current:**
    ```python
    if not msg.strip():
        print("Aborting commit due to empty AI commit message.", file=sys.stderr)
        raise ExitWithCode(1)
    ```

    **Problems:**
    1. "empty AI commit message" is misleading - implies AI-specific issue
    2. Duplicates Git's validation
    3. Prevents Git flags like `--allow-empty-message` from working
    4. We don't check for editor-flow messages (line 643-645) being empty - inconsistent

    **Fix:**
    Delete lines 588-590. Pass the message to Git as-is and let Git validate it.
    Git will print "Aborting commit due to empty commit message." if needed.

    **Optional:** Add one-line comment: `# Git will validate message is non-empty`

    **Consider:** Write integration test that verifies empty message is rejected
    (but by Git, not by our code).
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [588, 590],  // Redundant empty message check
    ],
  },
)
