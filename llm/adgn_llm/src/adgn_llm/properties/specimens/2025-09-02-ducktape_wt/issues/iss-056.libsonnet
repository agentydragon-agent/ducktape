local I = import '../../specimen_issues.libsonnet';

// iss-056: Collapse multi-line assert in tests/conftest.py
I.issueOneOccurrence(
  id='iss-056',
  rationale='Collapse multi-line assert into a concise single-line assertion for readability and brevity in test helpers. Suggest: `assert shutil.which("gitstatusd"), "integration tests require gitstatusd on PATH"`.',
  properties=['no-extra-linebreaks'],
  filesToRanges={
    'wt/tests/conftest.py': [[298,300]],
  },
)
