local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The --ui-port flag is defined and accepted but misleads users about a non-existent Management UI.

    In single-agent mode: the flag is completely unused (no UI app created).
    In multi-agent mode: the flag binds a stub FastAPI app with unimplemented features:
    - WebSocket at /ws/mcp returns "not_implemented" (server.py:287-289)
    - No web frontend exists (no HTML/JS/Svelte files for "Management UI")

    Log messages compound the problem:
    - "Management UI: http://{host}:{ui_port}" - suggests functional UI (doesn't exist)
    - "MCP: ws://{host}:{ui_port}/ws/mcp" - suggests working WebSocket (unimplemented)

    The flag's only functional use is binding uvicorn (cli.py:166), but the server serves
    nothing beyond stubs and proxies. This creates unnecessary complexity (two ports instead
    of one) and false expectations about Management UI capabilities.

    Fix: Remove --ui-port flag. Either implement the promised UI or consolidate all endpoints
    onto mcp-port.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/cli.py': [
      63,           // --ui-port flag definition
      72,           // ui_port parameter
      103,          // ui_port passed to _run_server
      116,          // ui_port parameter in _run_server
      160,          // Misleading log: "Management UI"
      161,          // Misleading log: WebSocket URL
      166,          // Only functional use: uvicorn bind
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [260, 270],   // create_management_ui_app docstring (claims "web interface")
      [283, 289],   // Unimplemented /ws/mcp WebSocket stub
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/mcp_bridge/cli.py'],
  ],
)
