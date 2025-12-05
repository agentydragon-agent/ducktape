local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 311-312 silently succeed when given an empty server name: "if name in ('',): return". This is wrong because if validation fails and an empty string reaches this point, the caller receives None (appearing like success) instead of a clear error.

    If the upstream validation at line 253 is reliable, this check is redundant and should be removed. If this is meant as a defensive check against validation failures, it should raise ValueError("server name cannot be empty") rather than silently returning. Silent success on invalid input masks bugs and makes debugging harder.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/compositor/server.py': [[311, 312]]},
)
