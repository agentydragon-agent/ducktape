local I = import '../../lib.libsonnet';

// iss-053: Consolidate pre-commit PTY read into a single drain loop
I.issue(
  snapshot='ducktape/2025-09-03-00',
  rationale=|||
    The PTY reader uses two loops (a poll loop until task.done() and a final drain loop). Since the
    drain loop already consumes remaining data until EOF/error, a single `while True` drain with
    clear exit conditions suffices and simplifies control flow.

    Suggestion: replace the poll+drain pair with one loop that reads, writes to the aggregator, and breaks
    on EOF/exception. Add a brief comment documenting the exit conditions.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[568, 583]],
  },
)
