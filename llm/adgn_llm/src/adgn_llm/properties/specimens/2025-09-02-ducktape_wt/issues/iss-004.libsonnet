local I = import '../../specimen_issues.libsonnet';

  // iss-004: Markdown inline formatting for environment variables
  I.issueOccurrencesFromLines(
    id='iss-004',
    rationale='In Markdown, format environment variables (e.g. PATH) with inline code.',
    properties=['inline-formatting'],
    linesByFile={
      'wt/README.md': [16, 18, 190],
    },
  )
