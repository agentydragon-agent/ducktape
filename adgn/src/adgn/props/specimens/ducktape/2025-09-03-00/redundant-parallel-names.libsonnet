local I = import '../../lib.libsonnet';

// Redundant parallel names in editor flow (final_text vs content_before)
I.issue(
  rationale= |||
    The editor flow uses redundant parallel variable names (`final_text` and `content_before`) that mirror each other
    without adding clarity. Keep a single source variable to reduce cognitive load and avoid confusion about which
    represents the canonical value.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[906, 922]],
  },
)
