local I = import '../../specimens/lib.libsonnet';

// iss-002: Unused --ui-port flag misleads users about non-existent Management UI
//
// Context:
// - CLI defines --ui-port flag (cli.py:63) with help text "Management UI port (WebSocket channels, no token auth)"
// - In single-agent mode: ui-port is completely unused (no UI app created at all)
// - In multi-agent mode: ui-port binds a stub FastAPI app that:
//   - Has /ws/mcp WebSocket endpoint that returns "not_implemented" (server.py:287-289)
//   - Has /api/agents endpoint that delegates to MCP server
//   - Has NO web frontend (no HTML/JS/Svelte files)
// - Log messages mislead users (cli.py:160-161):
//   - "Management UI: http://{host}:{ui_port}" - implies functional UI exists
//   - "MCP: ws://{host}:{ui_port}/ws/mcp" - implies WebSocket works (it doesn't)
//
// The flag is only functionally used to bind uvicorn server (cli.py:166), but the
// server serves nothing useful - just stubs and proxies to the real MCP server.
//
// Properties violated:
// 1. no-dead-code: Flag accepted but serves no real purpose (stub functionality only)
// 2. truthfulness: CLI help and log messages mislead about Management UI existence
// 3. least-power: Creates unnecessary separation (two ports) when one would suffice
//
// Fix: Remove --ui-port flag entirely. Either:
//   - Implement the Management UI with proper frontend, or
//   - Remove the stub and serve all endpoints on mcp-port

I.issueOneOccurrence(
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
  properties=['no-dead-code', 'truthfulness', 'least-power'],
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
)
