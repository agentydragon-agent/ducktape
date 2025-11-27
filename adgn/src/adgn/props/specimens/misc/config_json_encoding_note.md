# Note: Config JSON read uses implicit encoding

Context
- Specimen: 2025-08-29-pyright_watch_report
- File: pyright_watch_report.py
- Purpose: Loads a config candidate JSON if present.

Evidence
- At approx lines 46–52:
  - `return cand, json.loads(cand.read_text())`
  - read_text() is called without an explicit encoding, while later writes use `encoding="utf-8"`.

Risk
- Implicit locale-dependent decoding can break on non-UTF-8 locales or non-ASCII content.
- Asymmetry (writes with UTF-8, reads without encoding) can cause subtle failures.

Recommendation (generic, not applied yet)
- Read with an explicit encoding to match writes:
  - `json.loads(cand.read_text(encoding="utf-8"))`
  - or `with cand.open("r", encoding="utf-8") as f: data = json.load(f)`

Status
- Skipped for now per triage. This note records the observation and a safe remediation.

Next steps (when revisiting)
- Apply explicit UTF-8 to all config reads.
- Keep read/write encodings consistent across the file.
