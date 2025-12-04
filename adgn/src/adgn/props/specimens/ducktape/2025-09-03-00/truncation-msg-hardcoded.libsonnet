local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The truncation note is hardcoded as "[Context truncated to 100 KiB]" in multiple places, while the cap
    is driven by MAX_PROMPT_CONTEXT_BYTES. This duplicates the limit in string form and risks drift.

    Prefer a single source of truth: derive the human text from the cap (e.g., f"[Context truncated to {MAX_PROMPT_CONTEXT_BYTES // 1024} KiB]")
    or use a generic stable marker like "[Context truncated]". Keep the message in one place and reuse it.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [
      [135, 136],
      [154, 156],
      [174, 176],
      [193, 195],
      [201, 205],
    ],
  },
)
