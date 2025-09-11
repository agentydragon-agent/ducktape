local I = import '../../specimen_issues.libsonnet';

// iss-027-outside-workingdir-gate
// Factor outside-working-directory gating (relPath check + permission request) into a helper.

I.issueOneOccurrence(
  id='iss-027-outside-workingdir-gate',
  rationale='Both View and LS tools perform the same relative-path check and permission request when the target is outside the working directory. Factor this into a shared helper to avoid duplication and ensure consistent permission behavior and messaging.',
  properties=['no-dead-code'],
  filesToRanges={
    'internal/llm/tools/view.go': [[146,169]],
    'internal/llm/tools/ls.go': [[134,167]],
  },
)
