local I = import '../../specimens/lib.libsonnet';

// iss-034: Avoid mutable module-level singletons for Docker client/container
I.issueOneOccurrence(
  rationale=|||
    Module-level `_DOCKER_CLIENT` and `_CONTAINER_REF` introduce mutable global state that couples requests
    through hidden, process-wide singletons. This makes behavior order-dependent, complicates testing,
    and risks leaking configuration across calls.

    Prefer explicit dependency injection: pass a Docker client via parameters or a factory, or manage per-request
    context that resolves the container ref at call time. Keep state local to the request boundary.
  |||,
  // properties=[],
  gap_note='Add a property discouraging mutable global state/singletons; require DI or scoped contexts.',
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py': [[53, 58], [60, 71]],
  },
)
