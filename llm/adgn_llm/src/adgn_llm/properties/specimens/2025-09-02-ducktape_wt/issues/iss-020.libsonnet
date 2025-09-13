local I = import '../../specimen_issues.libsonnet';

// iss-020: Scoped try/except — do not silently swallow streaming errors
I.issueOccurrencesFromLines(
  rationale=|||
    Streaming hook output handler swallows all exceptions with `except Exception: pass`, discarding real errors.
    Either:
    - Catch only exact exceptions that have a specific reason to be ignored here (e.g., BrokenPipeError).
    Log them with context, and decide whether to re-raise or gracefully terminate stream.
    - Just not have any try-catch here at all and let "first, do no harm": i.e., surface errors by crashing
  |||,
  properties=['scoped-try-except'],
  linesByFile={
    'wt/wt/server/wt_server.py': [
      [2069, 2074],
    ],
  },
)
