local I = import '../../lib.libsonnet';

// fp-003-yolo-flag
// False positive: CLI flag `--yolo` is acceptable branding and should not be renamed.

I.falsePositive(
  rationale=|||
    A past critique suggested renaming the CLI flag `--yolo` (and local variable `yolo`) to a more
    descriptive predicate such as `--skip-permission-requests`. This is a false positive.

    "yolo mode" is intentionally branded and used consistently across the user-facing docs and UX
    as a short, memorable alias for the dangerous mode that automatically accepts permission requests.
    The flag help already documents its semantics clearly: "Automatically accept all permissions (dangerous mode)".

    It is acceptable to keep the public flag name `--yolo` as a tongue-in-cheek user-facing label while
    keeping any internal semantic name (e.g., skip-permissions) in code where helpful. No change required.
  |||,
  filesToRanges={
    'internal/cmd/root.go': [[29, 31], [132, 169]],
  },
)
