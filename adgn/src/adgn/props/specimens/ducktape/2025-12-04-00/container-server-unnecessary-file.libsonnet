local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The file `src/adgn/mcp/exec/docker/server.py` contains only `make_container_exec_server`, which is the sole user of `register_container` from container_session.py. This creates unnecessary indirection and file fragmentation:
    - The entire file is 36 lines for one thin wrapper function
    - `make_container_exec_server` just calls `EnhancedFastMCP()`, `make_container_lifespan()`, and `register_container()`
    - `register_container` is only called from this one place

    Either merge the functionality into container_session.py (making `register_container` the primary entry point) or find another justification for this separation. The current structure adds no value and makes the codebase harder to navigate.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/exec/docker/server.py': [[1, 36]]},
)
