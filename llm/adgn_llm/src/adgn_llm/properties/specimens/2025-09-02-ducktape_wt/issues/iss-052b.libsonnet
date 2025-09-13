local I = import '../../specimen_issues.libsonnet';

// iss-052b: Align implementation signatures with hookspecs
I.issueOneOccurrence(
  rationale='Align hook implementation signatures with hookspecs; remove `# type: ignore[override]` by matching signatures and prefer `pass` rather than `return None`. Suggested change for lines 31-36: remove the `# type: ignore[override]` and use a matching signature; change `return None` to `pass` in wt_init.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/plugins.py': [[31, 36]],
  },
)
