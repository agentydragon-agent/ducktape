local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Code guards debug logs with `if self.debug: ... logger.debug(...)`. Prefer leaving configuration to the logger:
    emit `logger.debug(...)` unconditionally and let handler levels/filters handle it. Guard only expensive
    formatting when necessary (or use logger.isEnabledFor(logging.DEBUG)). This keeps config centralized and
    removes redundant conditionals at call sites.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[1172, 1176]],
  },
)
