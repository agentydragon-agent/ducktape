local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The `_get_editor()` function spawns a subprocess (`git var GIT_EDITOR`) to get
    the configured editor, but pygit2 already provides direct access to git config
    through `repo.config`.

    **Problems:**

    1. **Subprocess overhead**: Spawning `git var` is slower than reading config directly
    2. **Unnecessary async**: Config access is synchronous, no need for async/await
    3. **Error-prone**: Must handle process exit codes, stdout decoding, stderr
    4. **Inconsistent**: Code uses pygit2 for everything else, but shells out for config
    5. **Already available**: `repo.config` provides dict-like access to git config

    **The correct approach:**

    Use pygit2's config API with a synchronous function that checks `repo.config.get('core.editor')`
    and falls back to environment variables (`EDITOR`, optionally `GIT_EDITOR`/`VISUAL`) and
    finally `'vi'`. This replicates `git var GIT_EDITOR` precedence without subprocess overhead.

    **Benefits:**

    1. **Faster**: No subprocess overhead
    2. **Simpler**: Synchronous function, no async/await needed
    3. **More readable**: Clear precedence order
    4. **Consistent**: Uses pygit2 like rest of codebase
    5. **Type-safe**: Returns `str` directly, no decoding needed
    6. **Fewer dependencies**: No need to ensure `git` binary is in PATH
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [649, 656],  // _get_editor: spawns subprocess instead of using pygit2 config
      [583, 583],  // Call site in _run_editor_flow
    ],
  },
)
