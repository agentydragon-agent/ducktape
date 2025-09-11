local I = import '../../specimen_issues.libsonnet';

  // iss-013: No dead code — logging_config
  I.issueOneOccurrence(
    id='iss-013',
    rationale='OperationLogger is dead code; JSONFormatter also becomes unused once it’s removed.',
    properties=['no-dead-code'],
    filesToRanges={
      'wt/wt/shared/logging_config.py': [[31, 94], [8, 29]],
    },
  )
