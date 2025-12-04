local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Bash tool timeout/limits documentation is inconsistent with implementation.

    - Prompt/help text claims default timeout is 30 minutes and that maximum is 10 minutes.
    - Actual implementation uses a default of 1 minute and a maximum of 10 minutes.

    Impact: Users get misleading guidance about default behavior; automated docs drift from behavior.

    Recommendation: Use a single source of truth (constants) and render the prompt/help text from those values at build time,
    so the displayed defaults/max align with the code.
  |||,
  filesToRanges={
    // Prompt/help and constants live here per code layout
    'internal/llm/tools/bash.go': null,
  },
)
