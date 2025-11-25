local I = import '../../specimens/lib.libsonnet';

// iss-003: Parsing passthru flags instead of using explicit argument

I.issueOneOccurrence(
  rationale= |||
    The `include_all_from_passthru()` function manually parses a list of passthrough
    flags to determine if `-a` or `--all` was passed, instead of having an explicit
    boolean argument.

    **Current implementation (core.py, lines 61-63):**
    ```python
    def include_all_from_passthru(passthru: list[str]) -> bool:
        """Return True if '-a' or '--all' flags are present."""
        return ("-a" in passthru) or ("--all" in passthru)
    ```

    **Used in 7 locations:**
    - `diffstat()` (line 170)
    - `build_prompt()` (line 190)
    - CLI: `_build_amend_diff()` (line 128) - takes passthru instead of bool
    - CLI: `_format_amend_comparison()` (line 145)
    - CLI: `_get_diff_to_commit()` (line 153)
    - CLI: `_stage_all_if_requested()` (line 524)
    - CLI: `prepare_commit_msg()` (line 698)

    **Similar pattern for --amend flag (cli.py, line 672):**
    ```python
    is_amend = "--amend" in passthru
    ```
    This manual parsing should also be replaced with an explicit CLI argument.

    **Problems:**

    1. **Fragile parsing**: String-in-list checking doesn't handle edge cases like
       `--all=false`, `-aV`, or other flag combinations correctly
    2. **Unclear interface**: Functions accept a generic `passthru: list[str]` but
       only care about specific flags
    3. **Coupling**: Core logic couples to CLI argument parsing conventions
    4. **Type safety**: Can't type-check or document that "passthru should contain -a/--all"
    5. **Inconsistency**: Different flags handled with different patterns (some parsed
       inline like `--amend`, some via helper functions like `-a`)

    **The correct approach:**

    Accept an explicit `include_all: bool` parameter:

    ```python
    def diffstat(repo: pygit2.Repository, include_all: bool) -> str:
        diff = _diff(repo, include_all)
        # ... rest of implementation
    ```

    Let the CLI layer handle parsing:
    ```python
    # In CLI code
    parser.add_argument('-a', '--all', dest='include_all', action='store_true')
    # ...
    result = diffstat(repo, args.include_all)
    ```

    **Benefits:**

    1. **Clear interface**: Functions declare exactly what they need
    2. **Type safety**: Boolean parameter is self-documenting and type-checkable
    3. **Separation of concerns**: Core logic doesn't know about CLI flags
    4. **Testability**: Easy to test with `include_all=True/False` directly
    5. **Robust**: No string parsing edge cases
  |||,
  properties=['explicit-over-implicit', 'separation-of-concerns'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [61, 63],   // include_all_from_passthru: fragile flag parsing
      [170, 170], // diffstat: using passthru instead of bool
      [190, 190], // build_prompt: using passthru instead of bool
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [52, 52],   // import of include_all_from_passthru
      [128, 128], // _build_amend_diff: takes passthru instead of bool
      [145, 145], // _format_amend_comparison: using passthru
      [153, 153], // _get_diff_to_commit: using passthru
      [524, 524], // _stage_all_if_requested: using passthru
      [672, 672], // is_amend = "--amend" in passthru: inline flag parsing
      [698, 698], // prepare_commit_msg: using passthru
    ],
  },
  gap_note= |||
    This finding illustrates the principle of **"explicit-over-implicit"**:
    Functions should accept explicit, typed parameters for the values they need
    rather than accepting generic containers and parsing out what they want.

    This is particularly important at architectural boundaries:
    - CLI layer should parse flags into typed values
    - Core/business logic should accept typed parameters
    - Don't pass raw `sys.argv` or `**kwargs` deep into the stack

    Related to "separation-of-concerns": core logic shouldn't know about
    command-line flag syntax.
  |||,
)
