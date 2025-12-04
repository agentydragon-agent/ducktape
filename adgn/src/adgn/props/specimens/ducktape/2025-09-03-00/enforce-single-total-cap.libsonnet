local I = import '../../lib.libsonnet';

// iss-051: Enforce a single total prompt cap (track remaining across blocks)
I.issue(
  snapshot='ducktape/2025-09-03-00',
  rationale=|||
    Current caps are applied per git output block (status / name-status / log / diff), so the assembled
    prompt can reach many× the nominal cap. Prefer a single accumulator-based total cap enforced over the
    fully assembled prompt, or track remaining bytes across calls to `_cap_append` to share the budget.

    This yields predictable size, avoids double work, and makes tradeoffs explicit between sections.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [
      [133, 137],  // _cap_append(status)
      [154, 156],  // _cap_append(name-status)
      [174, 176],  // _cap_append(log)
      [194, 195],  // _cap_append(diff)
      [201, 205],  // final cap enforcement
    ],
  },
)
