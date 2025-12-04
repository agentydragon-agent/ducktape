local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    Use pathlib.Path methods when operating on filesystem paths. Replace `os.path.exists(path)` with `Path(path).exists()` so the code consistently treats paths as Path-like objects and avoids mixing abstractions.

    Benefits:
    - Consistent use of Path improves readability and makes subsequent Path operations (open(), joinpath(), etc.) natural without extra conversions.
    - Avoids subtle differences between os.path handling and Path semantics across platforms.

    In this specimen the MCP config loader uses `os.path.exists(path)`; prefer `Path(path).exists()` (or accept a Path at the API boundary) to tighten the contract.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[32, 35]],
  },
)
