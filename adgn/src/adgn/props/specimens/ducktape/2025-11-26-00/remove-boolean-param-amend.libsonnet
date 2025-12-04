local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 539-547 define `_get_previous_message_if_amend()` which takes `is_amend: bool`
    and returns None if False. This is the same antipattern as issues 043.

    **Current:**
    ```python
    def _get_previous_message_if_amend(repo: pygit2.Repository, is_amend: bool) -> str | None:
        if not is_amend:
            return None
        try:
            commit = repo.head.peel(pygit2.Commit)
            return (commit.message or "").strip()
        except (KeyError, pygit2.GitError) as e:
            print(f"Error: Cannot amend - failed to retrieve previous commit message: {e}", file=sys.stderr)
            raise ExitWithCode(1)

    # Called at line 731:
    previous_message = _get_previous_message_if_amend(repo, is_amend)
    ```

    **Fix:** Remove boolean parameter, call only when amending:
    ```python
    def _get_previous_commit_message(repo: pygit2.Repository) -> str:
        """Get the message from HEAD commit (for amend)."""
        try:
            commit = repo.head.peel(pygit2.Commit)
            return (commit.message or "").strip()
        except (KeyError, pygit2.GitError) as e:
            print(f"Error: Cannot amend - failed to retrieve previous commit message: {e}", file=sys.stderr)
            raise ExitWithCode(1)

    # At call site (line 731):
    previous_message = _get_previous_commit_message(repo) if is_amend else None
    ```

    Or even simpler - inline at call site since it's called only once.

    **Benefits:**
    1. Function no longer wraps an if-statement
    2. Return type is non-nullable `str` (clearer semantics)
    3. Function name doesn't encode the condition ("if_amend")
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [539, 547],  // Function with boolean parameter
      731,  // Call site
    ],
  },
)
