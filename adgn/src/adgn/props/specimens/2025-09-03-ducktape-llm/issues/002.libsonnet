local I = import '../../specimens/lib.libsonnet';

// iss-002: Scoped try/except should not swallow errors
I.issueOccurrencesFromLines(
  rationale=|||
    Scoped try/except blocks swallow errors instead of failing loudly.
    Where there is no specific recovery/handling need, do not catch at all — let exceptions bubble normally.
    Where there is a specific reason to handle, catch only the narrow exception and do not swallow silently (log and/or re-raise as appropriate).
  |||,
  // properties=['scoped-try-except'],
  linesByFile={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [138, 157, 177, 196],
  },
)
