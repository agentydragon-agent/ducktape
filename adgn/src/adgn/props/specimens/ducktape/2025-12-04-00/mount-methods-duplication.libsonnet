local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Massive duplication between `mount_server()` (lines 251-279) and `mount_inproc()` (lines 280-309) in compositor/server.py. The two methods are almost identical, differing only in:

    1. The setup call: `await mount.setup_external(spec, ...)` vs `await mount.setup_inproc(server, ...)`
    2. The spec stored: `Mount(name=name, pinned=pinned, spec=spec)` vs `Mount(name=name, pinned=pinned, spec=None)`

    The duplicate code includes (~50 lines each):
    - State checking (CLOSED validation)
    - Name validation (regex pattern matching)
    - Prefix normalization (`prefix = prefix or name`)
    - Duplicate check under lock
    - Mount registration under lock
    - Proxy mounting on FastMCP surface
    - Mount listener notifications (identical STATE and MOUNTED events)
    - Exception-safety patterns

    **Additional finding**: The `prefix` parameter is never passed as non-None in any call site (ripgrep shows all calls use two arguments only). Lines 278 and 329 both do `prefix = prefix or name`, making the parameter effectively dead - it always equals `name`. This should be removed entirely.

    **Suggested refactoring**: Extract a shared `_mount_common()` helper that accepts a setup function/lambda, taking the Mount instance and performing setup. Both public methods would call this helper:
    - `mount_server` passes `lambda m: m.setup_external(spec, ...)`
    - `mount_inproc` passes `lambda m: m.setup_inproc(server, ...)`

    This would eliminate ~40 lines of duplication and improve maintainability.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/compositor/server.py': [
      [251, 279],  // mount_server method
      [280, 309],  // mount_inproc method
    ],
  },
)
