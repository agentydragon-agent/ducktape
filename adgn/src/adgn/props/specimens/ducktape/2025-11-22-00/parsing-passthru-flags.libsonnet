local I = import '../../lib.libsonnet';

// Merged: parsing-passthru-flags, parsing-message-flag-passthru
// Both describe manual parsing of CLI flags from passthru strings

I.issue(
  rationale= |||
    Functions manually parse `passthru: list[str]` with string checks to determine CLI flags:
    `include_all_from_passthru()` checks for `-a`/`--all` (core.py:61-63), `filter_commit_passthru()`
    removes those flags (cli.py:508-510), `_validate_no_message_flag()` checks `-m`/`--message`
    (cli.py:513-520), and inline checks for `--amend` (cli.py:672) and `-v`/`--verbose`
    (editor_template.py:77).

    This is fragile (doesn't handle `-m=value`, `-am` combined flags, `--all=false`), unclear
    interface (functions accept generic passthru but only care about specific flags), couples core
    logic to CLI syntax, no type safety (can't type-check "passthru should contain -a"), inconsistent
    handling (some validated, some checked, some filtered), and hard to test (must construct string lists).

    Use argparse/click to parse flags explicitly: `-a`/`--all` as `action='store_true'` → `bool`,
    `--amend`/`-v` similarly. Replace `passthru: list[str]` parameters with typed bools (`include_all: bool`).
    CLI framework handles all flag formats, functions declare exact needs, type-safe, and easier testing.
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
