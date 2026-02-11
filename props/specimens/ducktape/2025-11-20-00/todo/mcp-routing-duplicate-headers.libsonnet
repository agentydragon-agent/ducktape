local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    MCPRoutingMiddleware.dispatch rebuilds response headers as a dict using {k.decode(): v.decode()
    for k, v in headers}, which collapses multiple occurrences of the same header name. HTTP responses
    rely on lists of (name, value) pairs to preserve duplicates like multiple Set-Cookie headers, so
    converting to a dict silently discards all but the last value for each header name.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [[142, 142]],
  },
)
