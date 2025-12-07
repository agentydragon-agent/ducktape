local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    McpManager.from_config() and from_servers() start _LiveServer instances sequentially without
    cleanup on failure. If await h.start() raises on server N, or if _collect_tools_live() fails,
    the method propagates the exception without closing the already-started servers in handles,
    leaving MCP subprocesses running. The startup should clean up any already started servers on failure.
  |||,
  occurrences=[
    {
      files: {'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[191, 224]]},
      note: 'In from_config()',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py']],
    },
    {
      files: {'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[226, 258]]},
      note: 'In from_servers()',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py']],
    },
  ],
)
