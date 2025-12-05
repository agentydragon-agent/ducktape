local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Modules under packages that are executed via console_scripts should not carry a `#!/usr/bin/env python3`
    shebang or be executable; the packaging shim handles invocation. Keeping shebangs on importable modules
    is misleading and unnecessary. Remove the shebang from library modules; reserve shebangs for true scripts
    under bin/ (if any).
  |||,
  occurrences=[
    {
      files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [1] },
      note: 'shebang on library module exposed via console_scripts',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py': [1] },
      note: 'shebang on library module exposed via console_scripts',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_mcp_launch.py': [1] },
      note: 'shebang on library module exposed via console_scripts',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_mcp_launch.py']],
    },
    {
      files: { 'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py': [1] },
      note: 'shebang on library module exposed via console_scripts',
      expect_caught_from: [['llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py']],
    },
  ],
)
