local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 105-115 return fabricated string `"unknown"` when no server matches
    the URI. This fails silently: callers might not handle it specially, it
    could be used as an actual server name downstream, and bugs become harder
    to track (error happens far from source).

    Fix: raise `ValueError` with clear message including the URI and available
    servers. This fails fast and loud, provides context, and forces callers
    to handle the error case properly.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/notifications/buffer.py': [
      [105, 115],  // Returns "unknown" instead of raising exception
    ],
  },
)
