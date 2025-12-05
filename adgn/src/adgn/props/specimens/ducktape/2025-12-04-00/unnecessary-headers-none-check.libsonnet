local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 346-348 construct headers dict, then pass headers=headers or None to StreamableHttpTransport.
    The code should verify whether StreamableHttpTransport treats headers=None differently from headers={}.
    If they are equivalent, simplify to headers=headers (remove the "or None" check).
    This eliminates unnecessary complexity unless there's a semantic difference.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/compositor/server.py': [[346, 349]]},
)
