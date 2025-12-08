local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The docstring comment "Callers must pass a fully constructed ContainerOptions (no kwargs)" in `make_container_exec_server` is obvious and useless. The function signature already shows `opts: ContainerOptions` as a required parameter with no kwargs accepted for the opts itself.

    This comment adds no information beyond what the type annotation already communicates. Delete it.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/exec/docker/server.py': [[25, 25]]},
)
