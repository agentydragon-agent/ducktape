local I = import '../../specimen_issues.libsonnet';

// iss-052a: Hookspec docstring should be a concise one-liner
I.issueOneOccurrence(
  id='iss-052a',
  rationale='Oneline the wt_init hookspec docstring: keep concise API-focused docstrings for hookspecs. Suggested text: "Optional initialization hook; can modify config or set globals."',
  properties=['no-useless-docs'],
  filesToRanges={
    'wt/wt/plugins.py': [[23, 26]],
  },
)
