local I = import '../../specimens/lib.libsonnet';

// iss-043: Remove shebangs from library modules exposed via console_scripts
I.issueOccurrencesFromLines(
  rationale=|||
    Modules under packages that are executed via console_scripts should not carry a `#!/usr/bin/env python3`
    shebang or be executable; the packaging shim handles invocation. Keeping shebangs on importable modules
    is misleading and unnecessary. Remove the shebang from library modules; reserve shebangs for true scripts
    under bin/ (if any).
  |||,
  linesByFile={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [1],
    'llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py': [1],
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_mcp_launch.py': [1],
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py': [1],
  },
)
