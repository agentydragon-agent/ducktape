local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    RunningInfrastructure.close() collects errors as strings and returns them
    in CloseResult, requiring callers to check return value (running.py:72-91).

    Current pattern:
    errors: list[str] = []
    for sidecar in reversed(self._sidecars):
        try:
            await sidecar.detach()
        except Exception as e:
            errors.append(f"{type(sidecar).__name__}: {e}")
    # ... more error collection
    if errors:
        return CloseResult(drained=False, error="; ".join(errors))
    return CloseResult(drained=True)

    Problems:
    - Caller must remember to check result.error (easy to forget)
    - Exception information degraded to strings (no stack traces)
    - Can't distinguish different error types
    - Loses structured exception hierarchy
    - Error handling is opt-in, not automatic

    Should raise ExceptionGroup (Python 3.11+):
    exceptions: list[Exception] = []
    for sidecar in reversed(self._sidecars):
        try:
            await sidecar.detach()
        except Exception as e:
            exceptions.append(e)
    # ... more error collection
    if exceptions:
        raise ExceptionGroup("Failed to close infrastructure", exceptions)

    Benefits:
    - Errors can't be ignored (exceptions propagate by default)
    - Preserves full exception context and stack traces
    - Standard Python pattern for multiple concurrent errors
    - Type-safe: can catch and handle specific exception types
    - Forces explicit error handling at call site

    ExceptionGroup designed exactly for this use case: collecting multiple
    exceptions during cleanup/teardown operations.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/runtime/running.py': [
      [72, 91],     // close() method with error collection
    ],
  },
)
