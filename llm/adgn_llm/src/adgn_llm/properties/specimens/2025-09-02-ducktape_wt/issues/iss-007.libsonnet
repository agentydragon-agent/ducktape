local I = import '../../specimen_issues.libsonnet';

// iss-007: Scoped try/except
I.issueOneOccurrence(
  rationale=|||
    This code silently hides ImportError/AttributeError when loading plugins.
    Those would be real and severe errors that should:
      - At the very least be logged if nothing better is possible
      - Ideally (if interactive) they should trigger a loud crash
        - Easiest way to do that: just not catch these exceptions here at all
  |||,
  properties=[],
  filesToRanges={
    'wt/wt/plugins.py': [[59, 63]],
  },
)
