local I = import '../../specimens/lib.libsonnet';

// iss-031: No dead code — protocol dead declarations
I.issueOccurrencesFromLines(
  rationale='Dead/unused protocol declarations: ProgressUpdate (L426), SUPPORTED_METHODS (L497).',
  // properties=['no-dead-code'],
  linesByFile={
    'wt/wt/shared/protocol.py': [[426, 433, 'ProgressUpdate'], [497, 513, 'SUPPORTED_METHODS']],
  },
)
