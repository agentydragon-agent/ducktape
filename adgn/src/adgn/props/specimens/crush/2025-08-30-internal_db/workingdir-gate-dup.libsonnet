local I = import '../../lib.libsonnet';


I.issue(
  rationale='Both View and LS tools perform the same relative-path check and permission request when the target is outside the working directory. Factor this into a shared helper to avoid duplication and ensure consistent permission behavior and messaging.',
  filesToRanges={
    'internal/llm/tools/view.go': [[146, 169]],
    'internal/llm/tools/ls.go': [[134, 167]],
  },
  expect_caught_from=[['internal/llm/tools/view.go'], ['internal/llm/tools/ls.go']],
)
