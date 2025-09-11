local I = import '../../specimen_issues.libsonnet';

  // iss-024: No useless documentation or comments — trim conftest.py docstrings/comments
  I.issueOccurrencesFromLines(
    id='iss-024',
    rationale='Trim historical/obvious documentation; describe only current behavior; keep only non-obvious notes.',
    properties=['no-useless-docs'],
    linesByFile={
      'wt/tests/conftest.py': [
        [391, 394, 'Helper docstring includes historical workflow; trim to describe only current behavior.'],
        [426, 'Remove historical comment about removed fixture. It describes no longer relevant state of codebase. Not useful to keep.'],
        [302, 308, 'Shorten real_temp_repo docstring to a single descriptive line; drop compatibility notes.'],
        [312, 337, 'Trim real_env docstring and meta-comments; keep only non-obvious behavior.'],
      ],
    },
  )
