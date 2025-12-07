local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    McpManager.call_tool() has asymmetric calling conventions: stdio tools are awaited (L273),
    but local handlers are called synchronously (L280). This means local tools doing
    time.sleep(10) would block the event loop, while "sleep 10" in a stdio tool would not.
    Either local handlers should support async (call with await if coroutine detected), or
    the assymetry should at least be documented.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[266, 285]],
    'llm/adgn_llm/src/adgn_llm/mini_codex/local_server.py': [[7, 7]],
  },
  expect_caught_from=[['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py']],
)
