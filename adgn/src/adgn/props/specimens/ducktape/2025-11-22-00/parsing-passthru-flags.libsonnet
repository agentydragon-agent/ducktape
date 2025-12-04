local I = import '../../lib.libsonnet';

// Merged: parsing-passthru-flags, parsing-message-flag-passthru
// Both describe manual parsing of CLI flags from passthru strings

I.issue(
  rationale= |||
    Multiple functions manually parse passthrough flag lists to determine if specific
    CLI flags were passed, instead of having explicit typed arguments that the CLI
    framework parses.

    **Pattern: String-in-list checking for CLI flags**

    Functions accept generic `passthru: list[str]` and check for specific flags:
    - `include_all_from_passthru()` - checks for `-a`/`--all`
    - `filter_commit_passthru()` - removes `-a`/`--all` from passthru
    - `_validate_no_message_flag()` - checks for `-m`/`--message`
    - Inline checks for `--amend`, `-v`/`--verbose`

    **Examples of the pattern:**

    ```python
    # core.py:61-63
    def include_all_from_passthru(passthru: list[str]) -> bool:
        return "-a" in passthru or "--all" in passthru

    # cli.py:508-510
    def filter_commit_passthru(passthru: list[str]) -> list[str]:
        return [arg for arg in passthru if arg not in ["-a", "--all"]]

    # cli.py:513-520
    def _validate_no_message_flag(passthru: list[str]) -> None:
        if "-m" in passthru or "--message" in passthru:
            raise ValueError("Cannot use -m/--message with AI commit generation")

    # cli.py:672
    is_amend = "--amend" in passthru

    # editor_template.py:77
    include_verbose = ("-v" in passthru) or ("--verbose" in passthru)
    ```

    **Problems with manual parsing:**

    1. **Fragile**: String checking doesn't handle all edge cases:
       - `-m=value` (equals syntax)
       - `-am` (combined short flags)
       - `--all=false` (boolean flags with values)
       - Other flag combinations

    2. **Unclear interface**: Functions accept generic `passthru: list[str]` but
       only care about specific flags - interface doesn't document requirements

    3. **Coupling**: Core logic couples to CLI argument parsing conventions

    4. **Type safety**: Can't type-check or document "passthru should contain -a/--all"

    5. **Inconsistent handling**: Different patterns for similar operations:
       - `-m` is validated (rejected)
       - `-a` is checked and filtered
       - `--amend` is checked inline

    6. **Testing difficulty**: Hard to test without constructing string lists

    **The correct approach:**

    Use argparse/click to parse flags explicitly with typed parser arguments:
    - `-a`/`--all` as `action='store_true'` → `bool`
    - `-m`/`--message` as suppressed argument that validates to None
    - `--amend` as `action='store_true'` → `bool`
    - `-v`/`--verbose` as `action='store_true'` → `bool`

    Pass parsed booleans/values to functions instead of raw string lists.

    **Example refactored function signatures:**

    ```python
    # Before
    def diffstat(repo, passthru: list[str], **kwargs) -> str:
        include_all = include_all_from_passthru(passthru)
        ...

    # After
    def diffstat(repo, include_all: bool, **kwargs) -> str:
        ...

    # Before
    def _validate_no_message_flag(passthru: list[str]) -> None:
        if "-m" in passthru or "--message" in passthru:
            raise ValueError(...)

    # After (handled by argparse)
    parser.add_argument("-m", "--message", help=argparse.SUPPRESS)
    # argparse validates mutual exclusivity with AI mode
    ```

    **Benefits:**

    1. **Robust parsing**: CLI framework handles all flag formats correctly
    2. **Clear interface**: Functions declare exactly what they need
    3. **Type safety**: Boolean/typed parameters are self-documenting
    4. **Separation of concerns**: Core logic doesn't know about flag syntax
    5. **Consistent patterns**: All flags handled the same way
    6. **Easy testing**: Test with direct boolean values
  |||,
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
      [508, 510], // filter_commit_passthru: filters -a/--all from passthru
      [513, 520], // _validate_no_message_flag: fragile string parsing
      [524, 524], // _stage_all_if_requested: using passthru
      [672, 672], // is_amend = "--amend" in passthru: inline flag parsing
      [698, 698], // prepare_commit_msg: using passthru
    ],
    'adgn/src/adgn/git_commit_ai/editor_template.py': [
      [77, 77],   // include_verbose = ("-v" in passthru) or ("--verbose" in passthru)
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/core.py'],
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/git_commit_ai/editor_template.py'],
  ],
)
