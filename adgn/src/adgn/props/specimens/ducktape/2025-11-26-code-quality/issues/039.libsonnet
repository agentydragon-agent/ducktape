local I = import '../../specimens/lib.libsonnet';

// iss-039: Use pygit2.Repository directly, avoid gitdir variable

I.issueOneOccurrence(
  rationale=|||
    Lines 700-704 manually discover the git directory using `pygit2.discover_repository()`,
    then check if it's None, then create the Repository. Per pygit2's test suite and
    documentation, `Repository()` auto-discovers the .git directory by default (only
    disabled with RepositoryOpenFlag.NO_SEARCH flag).

    **Current:**
    ```python
    gitdir = pygit2.discover_repository(Path.cwd())
    if not gitdir:
        print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
        raise ExitWithCode(128)
    repo = pygit2.Repository(gitdir)
    ```

    **Correct approach:**
    ```python
    try:
        repo = pygit2.Repository(Path.cwd())
    except pygit2.GitError:
        print("fatal: not a git repository (or any of the parent directories)", file=sys.stderr)
        raise ExitWithCode(128)
    ```

    **Benefits:**
    1. Eliminates `gitdir` variable
    2. Simpler - one call instead of two
    3. More idiomatic - uses library's built-in discovery
    4. Repository automatically searches parent directories for .git

    **Evidence:** pygit2 test suite (test_repository.py:666-677) shows `Repository(subdir_path)`
    successfully discovers parent .git directories by default. Auto-discovery is only disabled
    when RepositoryOpenFlag.NO_SEARCH is explicitly passed.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [700, 704],  // Manual discovery may be unnecessary
    ],
  },
)
