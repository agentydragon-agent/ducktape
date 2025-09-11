local obj = {
  id: "iss-001",
  should_flag: true,
  rationale: |||
    Code uses legacy `typing` aliases (`List`/`Dict`/`Set`/`Tuple`).
    Switch to modern built‑in generics (`list`/`dict`/`set`/`tuple`) and using `collections.abc` for protocols like `Iterable`, to keep types concise and idiomatic.
  |||,
  properties: ['type-hints'],
  instances: [ { files: { "pyright_watch_report.py": [ { start_line: 30 }, { start_line: 36 }, { start_line: 90 }, { start_line: 192 }, { start_line: 198 }, { start_line: 211 } ] } } ],
};

obj
