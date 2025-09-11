local I = import '../../specimen_issues.libsonnet';

// iss-058: One-line wt_init hookspec docstring
I.issueOneOccurrence(
  id='iss-058',
  rationale='Oneline wt_init hookspec docstring: `"""Optional initialization hook; can modify config or set globals."""` — avoid multi-line docstrings for trivial hookspecs. Suggested one-liner: "Optional initialization hook; can modify config or set globals."',
  properties=['no-useless-docs'],
  filesToRanges={
    'wt/wt/plugins.py': [[24,26]],
  },
)

