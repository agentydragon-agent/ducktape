local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    For simple file I/O, prefer using Path.read_text()/Path.write_text() or Path.open() instead of calling open(str(path), ...) manually.

    Benefits:
    - Concise one-liners for common patterns.
    - Keeps types as Path objects and avoids repeated str() conversions.
    - Clearer intent and small performance/readability improvements.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/agent.py': [[85, 92]],
  },
)
