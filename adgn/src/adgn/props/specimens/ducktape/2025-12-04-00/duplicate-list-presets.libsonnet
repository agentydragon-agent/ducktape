local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `list-presets` functionality is duplicated: both a `--list-presets` boolean flag on `cmd_run` and a separate `list-presets` command exist.

    Both implementations call the same `_print_presets()` helper and provide identical functionality:
    - Line 605: `list_presets: bool = typer.Option(False, "--list-presets", ...)`
    - Line 614-616: `if list_presets: _print_presets(); return`
    - Line 680-683: `@app.command("list-presets")` that calls `_print_presets()`

    **Why this is problematic:**

    1. **Inconsistent UX**: Two ways to do the same thing confuses users
    2. **Maintenance burden**: Changes to listing logic need updates in two places
    3. **Error message inconsistency**: Line 573 says "Use --list-presets" but `adgn-properties list-presets` also works
    4. **Flag pollution**: The `run` command has many parameters; info-only flags clutter the interface

    **Recommended fix:**

    Remove the `--list-presets` flag from `cmd_run` and keep only the dedicated `list-presets` command:
    - Delete line 605 (`list_presets` parameter)
    - Delete lines 614-616 (flag handling)
    - Update line 573 error message: "Use --list-presets" → "Use 'adgn-properties list-presets'"
    - Update line 592 help text: "see --list-presets" → "see 'adgn-properties list-presets'"

    **Rationale for keeping command over flag:**

    - Dedicated commands are clearer: `list-presets` is self-documenting
    - Flags that exit early are anti-patterns (they're not really options, they're alternative operations)
    - Consistent with other info commands like `snapshot list`, `snapshot dump`
    - Separates concerns: `run` is for execution, `list-presets` is for discovery
  |||,
  filesToRanges={
    'adgn/src/adgn/props/cli_app/main.py': [
      573,           // Error message mentioning --list-presets
      592,           // Help text in --preset option
      605,           // --list-presets flag definition
      [614, 616],    // Flag handling (early return)
      [680, 683],    // list-presets command definition
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/props/cli_app/main.py'],  // See both flag and command, recognize duplication
  ],
)
