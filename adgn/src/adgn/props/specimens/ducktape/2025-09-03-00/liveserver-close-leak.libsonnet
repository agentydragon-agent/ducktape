local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    _LiveServer.close() awaits session.__aexit__() and only afterwards closes the stdio
    transport context manager. If the session close raises, the stdio cleanup never runs,
    leaking subprocess pipes and file descriptors.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[95, 101]],
  },
)
