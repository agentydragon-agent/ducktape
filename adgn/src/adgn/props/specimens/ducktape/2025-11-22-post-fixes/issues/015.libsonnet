local I = import '../../specimens/lib.libsonnet';

// iss-015: Spawning subprocess to get GIT_EDITOR instead of using pygit2

I.issueOneOccurrence(
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
  properties=['use-platform-primitives', 'avoid-subprocess'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [649, 656],  // _get_editor: spawns subprocess instead of using pygit2 config
      [583, 583],  // Call site in _run_editor_flow
    ],
  },
  gap_note= |||
    This finding illustrates **"avoid-subprocess"**: when a library provides an API
    for accessing data, use it instead of spawning a subprocess to run external commands.

    Subprocess calls should be reserved for:
    - Operations the library doesn't provide (e.g., running external tools)
    - Interacting with external systems (e.g., calling `docker`, `kubectl`)
    - User-configurable commands (e.g., running the editor itself)

    Config access is a core library feature - pygit2 provides `repo.config` specifically
    to avoid needing to shell out to `git config` or `git var`.

    Related to "use-platform-primitives": pygit2 wraps libgit2, which provides
    comprehensive git functionality including config access. Use the library's native
    APIs rather than falling back to subprocess calls.

    Benefits of avoiding subprocess:
    - Faster (no process spawn overhead)
    - Simpler error handling (no exit codes, no stdout/stderr)
    - Type-safe (library returns typed values)
    - Cross-platform (library handles platform differences)
    - More testable (can mock config without mocking subprocess)
  |||,
)
