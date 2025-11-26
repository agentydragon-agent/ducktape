local I = import '../../specimens/lib.libsonnet';

// iss-007: Use walrus for inline returncode/condition checks
I.issueWithOccurrences(
  rationale=|||
    Prefer the walrus operator (:=) for concise inline checks when a value is computed once and immediately tested.
    Examples here: editor return code and subprocess return code after create_subprocess_exec can be checked inline, reducing temporary variables and making control flow clearer.
    For single-use path conditions, consider using walrus when it improves clarity without harming readability.
  |||,
  occurrences=[
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[927, 933]] }, note: 'Inline editor returncode: if (rc := await editor_proc.wait()) != 0: ...' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[599, 606]] }, note: 'Inline subprocess returncode: if (rc := await proc.wait()) != 0: ...' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[448, 451]] }, note: 'Cache.get: single-use path condition can use walrus when helpful' },
  ],
)
