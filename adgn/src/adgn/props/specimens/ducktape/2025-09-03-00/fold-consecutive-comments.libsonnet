local I = import '../lib.libsonnet';

// iss-042: Fold consecutive comment lines into a single concise line
I.issue(
  snapshot='ducktape/2025-09-03-00',
  rationale=|||
    Two consecutive comment lines describe a single obvious condition; fold them into one concise
    comment immediately above the code to avoid line waste while preserving clarity.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[625, 627]],
  },
)
