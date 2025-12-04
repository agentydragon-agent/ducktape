local I = import '../../lib.libsonnet';

// iss-011: Redundant str() conversion when calling discover_repository()

I.issue(
  rationale= |||
    The code calls `str(Path.cwd())` before passing to `pygit2.discover_repository()`,
    but that function accepts both `str` and `Path` objects. The conversion is redundant.

    **Current implementation (cli.py line 662, minicodex_backend.py line 163):**
    ```python
    gitdir = pygit2.discover_repository(str(Path.cwd()))
    ```

    **pygit2 signature:**
    ```python
    def discover_repository(
        path: str | Path, across_fs: bool = False, ceiling_dirs: str = ...
    ) -> str | None: ...
    ```

    **Problems:**

    1. **Redundant conversion**: `Path` is already accepted, no need to convert to `str`
    2. **Less readable**: Extra `str()` call adds noise
    3. **Type loss**: Converting to string loses type information that could be useful
    4. **Convention confusion**: Suggests the API requires strings when it doesn't

    **The correct approach:**

    Pass `Path` objects directly:

    ```python
    gitdir = pygit2.discover_repository(Path.cwd())
    ```

    **Benefits:**

    1. **Simpler**: One fewer function call
    2. **Clearer intent**: We're passing a path, not a string
    3. **Type safe**: Keeps the `Path` type until the API boundary
    4. **Consistent**: Use `Path` objects throughout, convert only when required

    **General principle:**

    When an API accepts `str | Path`, prefer passing `Path` objects directly rather
    than converting to `str`. Only convert when:
    - The API requires exactly `str` (not a union)
    - You need string operations (splitting, regex, etc.)
    - Logging/formatting requires string representation
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [662, 662],  // str(Path.cwd()) in discover_repository call
    ],
    'adgn/src/adgn/git_commit_ai/minicodex_backend.py': [
      [163, 163],  // str(Path.cwd()) in discover_repository call
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/git_commit_ai/minicodex_backend.py'],
  ],
)
