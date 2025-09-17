local I = import '../../specimens/lib.libsonnet';

// iss-052: Default cap/note inside _cap_append to avoid repetitive args
I.issueOneOccurrence(
  rationale=|||
    Calls like `_cap_append(parts, chunk, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated…]")` repeat the same
    constants at each site. Prefer giving `_cap_append` sensible defaults (or deriving the note from the cap)
    so callers only pass the varying pieces. This reduces duplication and drift risk across call sites.
  |||,
  // properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [
      [133, 137],
      [154, 156],
      [174, 176],
      [194, 195],
    ],
  },
)
