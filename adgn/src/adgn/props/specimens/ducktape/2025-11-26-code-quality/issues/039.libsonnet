local I = import '../../specimens/lib.libsonnet';

// iss-039: Use pygit2.Repository directly, avoid gitdir variable

I.issueOneOccurrence(
  rationale=|||
    Lines 700-704 manually discover the git directory, then check if it's None, then
    create the Repository. Check if `pygit2.Repository()` can discover automatically.

    **Current:**
    ```python
    gitdir = pygit2.discover_repository(Path.cwd())
    if not gitdir:
        print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
        raise ExitWithCode(128)
    repo = pygit2.Repository(gitdir)
    ```

    **Investigation needed:** Check if either of these works:
    - `pygit2.Repository(Path.cwd())` (auto-discovers from current dir)
    - `pygit2.Repository()` (auto-discovers from current dir)

    **If auto-discovery works:**
    ```python
    try:
        repo = pygit2.Repository(Path.cwd())  # Or just Repository()
    except pygit2.GitError:
        print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
        raise ExitWithCode(128)
    ```

    **Benefits:**
    1. Eliminates `gitdir` variable
    2. Simpler - one call instead of two
    3. More idiomatic - let library handle discovery and error reporting

    **If auto-discovery doesn't work:** Close this issue as invalid.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [700, 704],  // Manual discovery may be unnecessary
    ],
  },
)
