local I = import '../../lib.libsonnet';

// Related issue: pydantic-read-path.libsonnet (input side of persistence boundary handling)

I.issue(
  rationale= |||
    Pre-serialization of Pydantic models before passing to persistence layer.

    Calls model_dump() at caller site (lines 102-103, 110, 145-146) before passing
    to persistence methods. This violates separation of concerns - caller shouldn't
    know about persistence format.

    Anti-pattern: Serialization at caller site instead of callee. Correct approach:
    append_event should accept typed EventRecord payload, ResponsePayload should
    accept Response model, and serialization should happen inside persistence layer.

    Benefits:
    - Type safety preserved across call boundary
    - Single serialization point (DRY)
    - Clearer responsibility boundaries
    - Caller doesn't need to know persistence format
    - Easier to change serialization strategy later
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/handler.py': [
      [102, 103],
      110,
      [145, 146],
    ],
  },
)
