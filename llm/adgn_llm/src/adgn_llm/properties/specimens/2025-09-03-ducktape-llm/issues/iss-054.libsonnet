local I = import '../../specimen_issues.libsonnet';

// iss-054: Avoid double-gating debug logs; rely on logger configuration
I.issueOneOccurrence(
  rationale= |||
    Code guards debug logs with `if self.debug: ... logger.debug(...)`. Prefer leaving configuration to the logger:
    emit `logger.debug(...)` unconditionally and let handler levels/filters handle it. Guard only expensive
    formatting when necessary (or use logger.isEnabledFor(logging.DEBUG)). This keeps config centralized and
    removes redundant conditionals at call sites.
  |||,
  properties=['minimize-nesting'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[1172,1176]],
  },
)
