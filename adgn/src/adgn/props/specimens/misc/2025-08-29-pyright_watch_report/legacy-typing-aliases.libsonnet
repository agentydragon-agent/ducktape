local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Code uses legacy `typing` aliases (`List`/`Dict`/`Set`/`Tuple`).
    Switch to modern built‑in generics (`list`/`dict`/`set`/`tuple`) and using `collections.abc` for protocols like `Iterable`, to keep types concise and idiomatic.
  |||,
  filesToRanges={
    'pyright_watch_report.py': [30, 36, 90, 192, 198, 211],
  },
)
