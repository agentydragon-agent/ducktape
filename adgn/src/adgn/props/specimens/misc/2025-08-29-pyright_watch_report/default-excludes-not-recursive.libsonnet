local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Default exclude patterns are not recursive, so nested files under these directories are still included.

    In pyright_watch_report.py, excludes like "build", "dist", and ".mypy_cache" are used as literal patterns.
    With fnmatch on relative paths, a pattern of "dist" matches only a path named exactly "dist" — it does not match
    "dist/foo.py". As a result, files within these directories are not excluded.

    Example: 'dist/foo.py' will not be excluded by the pattern 'dist'.

    Note: Correct fix here would depend on specifics of how the program should behave and potential differences
    in matching semantics between python and pyrightconfig.
  |||,
  filesToRanges={
    // Defaults that include non-recursive excludes
    'pyright_watch_report.py': [
      [204, 214],  // default exclude list with 'build', 'dist', '.mypy_cache'
      [60, 76],    // expand_include_patterns exists, but no equivalent for excludes
      [134, 141],  // exclude matching applies patterns literally via fnmatch
    ],
  },
)
