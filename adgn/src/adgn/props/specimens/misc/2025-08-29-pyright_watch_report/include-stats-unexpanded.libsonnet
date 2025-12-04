local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Per-include stats are computed against the original, unexpanded include patterns, while the
    scan itself expands plain directory includes. This causes counts to be wrong (or zero) for
    includes like "src" that expand to "src/**" during the scan but are later matched literally as
    "src" when computing per-include kept/unique.

    Where:
    - expand_include_patterns (lines 60–75) turns:
      - "." → "**/*"
      - "src" → "src/**"
      - "src/" → "src/**"
      - Any pattern with glob metachar (* ? [) → unchanged
    - gather_files_single_pass uses the expanded include set for the walk (lines ~100–105).
    - per-include kept/unique stats (lines 227–245) iterate the original include list and call
      matches_any(rel(p, root), [pat]) with the unexpanded pattern.

    Illustrated example:
    - include = ["src", "tests/**/*.py"]
    - expand_include_patterns(include) = ["src/**", "tests/**/*.py"]  # used for traversal
    - kept_union contains files like "src/pkg/a.py"
    - per-include kept phase uses the original "src" (not "src/**"), so fnmatch("src/pkg/a.py", "src") = false
      → the kept/unique counts for "src" are under-reported.

    Acceptance criteria:
    - Compute per-include kept and per-include unique against the expanded include set (same rules used
      by the traversal), while preserving the original labels for display.
      For example, precompute:
        expanded = expand_include_patterns(include)
        label_map = { original: expanded_i }
      then use label_map[original] for matches_any in both the kept and unique computations, but print
      "original" in output tables.
    - Keep normalize_pattern behavior consistent across both phases.
  |||,
  filesToRanges={
    'pyright_watch_report.py': [[60, 76], [96, 105], [227, 245]],
  },
)
