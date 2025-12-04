local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    `LocalAgentRuntime` has lifecycle issues: missing type annotations
    (ui_bus, connection_manager at 81-82), "may be initialized" antipattern
    (session/agent nullable at 85-88, runtime checks at 155-158), incomplete
    cleanup (close() doesn't null fields at 160-165), and not being a proper
    context manager despite having start()/close() methods.

    "May be initialized" antipattern impact: object exists but isn't usable
    (half-initialized), every method must check initialization, type system
    can't help (fields are `T | None`), easy to forget start() call.

    Solutions: (1) async context manager (move start() logic to __aenter__,
    cleanup to __aexit__, automatic lifecycle, strong types, guaranteed
    cleanup), or (2) factory pattern (classmethod create() with async init,
    manual lifecycle but strong types).

    Current approach: manual unclear lifecycle, weak type safety, incomplete
    cleanup.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/local_runtime.py': [
      [81, 82],   // Missing type annotations for ui_bus, connection_manager
      [85, 88],   // May-be-initialized antipattern (session/agent nullable)
      [90, 153],  // start() method should be __aenter__
      [155, 158], // run() has unnecessary None check
      [160, 165], // close() doesn't null out session/agent
    ],
  },
)
