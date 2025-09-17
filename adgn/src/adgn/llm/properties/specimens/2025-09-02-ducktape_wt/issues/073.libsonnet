local I = import '../../specimens/lib.libsonnet';

// iss-073: Remove duplicated conditional block in wt_server
I.issueOneOccurrence(
  rationale='Redundant conditional block duplicated (same membership check appears twice); remove the duplicate branch to keep logic single-sourced and avoid divergence.',
  // properties=['minimize-nesting'],
  gap_note='GAP: Choose a consistent layer for conversion (e.g., relative→absolute) and apply it symmetrically across inputs; this mirrors the MIN_GIT_REPO_FIELDS repeated-check issue—bundle the gating/validation in one place.',
  filesToRanges={
    'wt/wt/server/wt_server.py': [[1425, 1430]],
  },
)
