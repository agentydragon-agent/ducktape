local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 46-51 silently swallow config read/parse errors in `load_config`. The function
    iterates candidate config files and uses `try/except Exception: pass` to skip any that
    fail to read or parse, continuing to the next candidate.

    Problems: silently discards explicit user intent when `--config` is provided, hides real
    configuration errors, broken files indicate issues users should see.

    Fix: let exceptions propagate (fail-fast) or catch and re-raise with context. Do not
    silently continue to the next candidate.
  |||,
  filesToRanges={
    'pyright_watch_report.py': [[46, 51]],
  },
)
