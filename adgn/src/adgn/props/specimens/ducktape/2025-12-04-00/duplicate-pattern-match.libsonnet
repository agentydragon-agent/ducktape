local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The expression "any(matches_pattern(f, pattern) for pattern in <list>)" appears
    twice in apply_gitignore_patterns (lines 38 and 42). This should be extracted to
    a local helper function to eliminate duplication and improve readability. The helper
    could be named something like matches_any_pattern(path, patterns).
  |||,
  filesToRanges={'adgn/src/adgn/props/cli_app/cmd_build_bundle.py': [[38, 42]]},
)
