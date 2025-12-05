local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[['adgn/src/adgn/agent/mcp_bridge/auth.py'], ['adgn/src/adgn/agent/mcp_bridge/server.py'], ['adgn/src/adgn/agent/runtime/builder.py'], ['adgn/src/adgn/agent/runtime/infrastructure.py'], ['adgn/src/adgn/agent/runtime/local_runtime.py'], ['adgn/src/adgn/agent/server/mcp_routing.py']],
  rationale= |||
    Six files have imports inside functions instead of at module top, violating PEP 8:
    auth.py line 180 imports json inside `_create_error_response`; server.py lines
    438-439 and 475-476 import FastAPI/auth modules inside functions; builder.py,
    infrastructure.py, local_runtime.py, and mcp_routing.py have similar patterns.

    Problems: Violates PEP 8 style guidelines, hides dependencies (harder to see all
    imports at a glance), import errors caught at runtime instead of module load time,
    worse for static analysis tools, usually indicates bad module organization or
    premature optimization.

    Move all runtime imports to the top of each file. If avoiding circular imports,
    restructure modules to eliminate the cycle or use TYPE_CHECKING guards for type
    annotations only. Benefits: PEP 8 compliance, immediate import error detection,
    clearer dependency visibility, better static analysis.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      180,
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [438, 439],
      [475, 476],
    ],
    'adgn/src/adgn/agent/runtime/builder.py': [
      46,
    ],
    'adgn/src/adgn/agent/runtime/infrastructure.py': [
      67,
    ],
    'adgn/src/adgn/agent/runtime/local_runtime.py': [
      40,
    ],
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [23, 24],
    ],
  },
)
