local I = import '../../specimens/lib.libsonnet';

// iss-009: Parsing -m/--message flag from passthru instead of explicit argument

I.issueOneOccurrence(
  rationale= |||
    The `_validate_no_message_flag()` function manually parses the passthrough flags
    to detect if `-m`/`--message` was passed, instead of having an explicit argument
    that the CLI framework parses.

    This is part of a larger pattern where multiple functions parse passthru strings:
    - `include_all_from_passthru()` - checks for `-a`/`--all`
    - `filter_commit_passthru()` - removes `-a`/`--all` from passthru
    - `_validate_no_message_flag()` - checks for `-m`/`--message`

    **Problems:**

    1. **Fragile parsing**: String checking doesn't handle all edge cases (e.g.,
       `-m=value`, short flag combinations like `-am`)
    2. **Unclear interface**: Functions accept generic `passthru: list[str]` but
       only care about specific flags
    3. **Coupling**: Core logic couples to CLI argument parsing conventions
    4. **Type safety**: Can't type-check or document "passthru may contain -m"
    5. **Inconsistent handling**: `-m` is validated (rejected), but `-a` is checked
       and filtered - different patterns for similar operations

    **The correct approach:**

    Use argparse to parse flags explicitly with typed parser arguments (`-a`/`--all`
    as `action='store_true'`, `-m`/`--message` as a suppressed argument that validates
    to None). Pass parsed booleans/values to functions instead of raw string lists.

    **Benefits:**

    1. **Robust parsing**: CLI framework handles all flag formats correctly
    2. **Clear interface**: Functions declare exactly what they need
    3. **Type safety**: Boolean/typed parameters are self-documenting
    4. **Separation of concerns**: Core logic doesn't know about flag syntax
    5. **Consistent patterns**: All flags handled the same way

    **Related functions (cli.py:508-520, core.py:61-63):**
    All three passthru-parsing functions should be replaced with proper CLI argument parsing.
  |||,
  properties=['explicit-over-implicit', 'separation-of-concerns', 'robust-parsing'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [513, 520],  // _validate_no_message_flag: fragile string parsing
      [508, 510],  // filter_commit_passthru: filters -a/--all from passthru
    ],
  },
  gap_note= |||
    This finding illustrates **"robust-parsing"**: when accepting structured inputs
    (command-line flags, configuration files, API parameters), use a proper parser
    or schema validator rather than manual string checking.

    Benefits of robust parsing:
    - Handles edge cases (flag formats, escaping, encoding)
    - Provides clear error messages
    - Documents expected format through schema/types
    - Enables validation before business logic runs

    Related to "explicit-over-implicit": explicit parsed arguments are better than
    implicit string inspection.

    This issue is closely related to issue 003 (include_all_from_passthru) - both
    should be addressed by refactoring to proper CLI argument parsing.
  |||,
)
