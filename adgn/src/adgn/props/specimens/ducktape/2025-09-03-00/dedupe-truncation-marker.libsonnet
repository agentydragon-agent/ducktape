local I = import '../../lib.libsonnet';

I.issue(
  expect_caught_from=[
    ['llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py'],
    ['llm/adgn_llm/src/adgn_llm/mini_codex/cli.py'],
  ],
  rationale=|||
    Truncation/timeout handling is duplicated and can lose the TIMEOUT marker:
    - Both modules implement `_truncate_bytes` and call it in success/timeout branches.
    - In timeout paths, code appends "[TIMEOUT]" before truncation; the marker can be truncated away.
    - The "[TRUNCATED]" literal appears inline in multiple places; hoist to a single constant.

    Recommended:
    - Factor a common post-processing step: `truncate_outputs(stdout, stderr, timed_out)` used in both branches.
    - Append "[TIMEOUT]" after truncation (ensuring room for the marker), so the signal is never lost.
    - Hoist markers to constants (e.g., `TRUNCATED_MARKER`, `TIMEOUT_MARKER`) and reuse.
  |||,
  filesToRanges={
    // TIMEOUT before truncation; duplicate truncate calls (timeout branch)
    'llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py': [[37, 46], [18, 22]],
    'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[96, 106], [79, 83]],
  },
)
