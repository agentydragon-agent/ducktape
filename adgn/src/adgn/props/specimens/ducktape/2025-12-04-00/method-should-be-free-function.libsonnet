local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Method _fm_transport_from_spec at lines 343-352 is an instance method but accesses no instance state.
    It's a pure transformation function: MCPServerTypes → ClientTransport.
    This should be a module-level function outside the class, not a method.
    As a free function, it's easier to test in isolation and signals that it has no side effects or class dependencies.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/compositor/server.py': [[343, 352]]},
)
