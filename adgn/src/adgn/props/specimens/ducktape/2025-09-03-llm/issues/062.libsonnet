local I = import '../../specimens/lib.libsonnet';

// iss-062: Use walrus to simplify Cache.get
I.issueOneOccurrence(
  rationale=|||
    `path = self.dir / f"{key}.txt"; return path.read_text() if path.exists() else None` can be
    simplified with the walrus operator to bind and test in one expression:

      return (p.read_text() if (p := self.dir / f"{key}.txt").exists() else None)

    This removes a one-off local and keeps the condition compact.
  |||,
  // properties=['walrus'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[448, 451]],
  },
)
