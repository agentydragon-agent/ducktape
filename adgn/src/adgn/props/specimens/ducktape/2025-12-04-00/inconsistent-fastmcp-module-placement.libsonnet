local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    FastMCP enhancement modules are inconsistently placed: `notifying_fastmcp.py` lives at the top level of `src/adgn/mcp/`, while `fastmcp_flat.py` lives under `src/adgn/mcp/_shared/`.

    This creates confusion about where FastMCP enhancements should be located. The `_shared/` directory is unclear in purpose and splits related functionality. Developers must search multiple locations to understand the full set of FastMCP enhancements available.

    All FastMCP enhancements should be co-located in a single namespace (e.g., `src/adgn/mcp/enhanced/`) for clarity and discoverability.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/notifying_fastmcp.py': [[1, 10]],
    'adgn/src/adgn/mcp/_shared/fastmcp_flat.py': [[1, 10]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/mcp/notifying_fastmcp.py', 'adgn/src/adgn/mcp/_shared/fastmcp_flat.py'],
  ],
)
