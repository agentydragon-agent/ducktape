local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    McpManager.close() (lines 302-304) only closes stdio handles and never calls close() on LocalServer
    instances in _state.local_servers, despite LocalServer.close() existing for cleanup (local_server.py:23-24).
    The instances are never closed anywhere in the codebase (verified: Agent.close() delegates to
    McpManager.close(), and no other code calls LocalServer.close()), so resources leak across agent runs.
    The API design is unclear about lifecycle ownership.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py': [[302, 304]],
    'llm/adgn_llm/src/adgn_llm/mini_codex/local_server.py': [[23, 24]],
  },
  expect_caught_from=[['llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py', 'llm/adgn_llm/src/adgn_llm/mini_codex/local_server.py']],
)
