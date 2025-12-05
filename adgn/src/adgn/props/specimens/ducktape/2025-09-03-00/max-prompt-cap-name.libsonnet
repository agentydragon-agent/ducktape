local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The constant name `MAX_PROMPT_CONTEXT_BYTES` uses two near-synonyms in this code path ("prompt" and "context").
    Either pick one term and scope it correctly, or enforce a true global prompt cap:

    Options:
    - Rename to reflect true scope (per-block cap): e.g., `MAX_PROMPT_GIT_OUTPUT_BYTES` (applies to each appended block)
    - Or adopt a global `MAX_PROMPT_BYTES` and enforce an overall cap, leaving block-level caps as internal helpers

    This reduces ambiguity, communicates scope precisely, and prevents misinterpretation.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[60, 60], [135, 137], [155, 156], [175, 176], [194, 195], [201, 205]],
  },
)
