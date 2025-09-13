local I = import '../../specimen_issues.libsonnet';

// iss-012: Pass pathlib.Path objects to PathLike-accepting APIs; avoid redundant str(path) casts
I.issueWithOccurrences(
  rationale= |||
    Many stdlib and library APIs accept os.PathLike objects (pathlib.Path). Prefer passing Path objects directly instead of calling str(path) everywhere.

    Why this matters:
    - Stripping Path -> str casts reduces noise and one-off conversions.
    - Passing Path preserves richer semantics (e.g., platform-specific paths, pathlike wrappers) and is less error-prone.
    - Modern APIs (subprocess, os.open, many stdlib functions) accept Path objects and will do the correct conversion; explicit str() casts are unnecessary.
  |||,
  properties=['pathlib'],
  occurrences=[
    { files: { 'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/kernel_exec.py': [[44,44]] }, note: 'os.open(log_path, ...) — pass Path directly' },
    { files: { 'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_mcp_launch.py': [[47,47], [57,57]] }, note: 'subprocess args include str(path) casts — pass Path objects where supported' },
    { files: { 'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[231,231], [243,243]] }, note: 'subprocess invocation building args: avoid converting Path -> str before passing to subprocess' },
  ],
)
