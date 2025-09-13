local I = import '../../specimen_issues.libsonnet';

// iss-040: Quoted forward references; prefer annotations from __future__
I.issueOneOccurrence(
  rationale='WorktreeRuntime uses quoted forward references ("GitstatusdClient", "PRService"); should use `from __future__ import annotations`, reorder definitions, and annotate directly.',
  properties=['type-hints'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[424, 428]],
  },
)
