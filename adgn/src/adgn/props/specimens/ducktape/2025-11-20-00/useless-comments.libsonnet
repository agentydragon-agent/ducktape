local I = import '../../lib.libsonnet';

// Extracted from redundant-documentation.libsonnet (useless break comment)

I.issue(
  rationale= |||
    Comment states what break statement obviously does: "Break sender loop - connection
    is broken". The break is inside an exception handler after logging "WebSocket send
    failed", so context is already clear.

    Comments should explain why, not what. This comment adds no information beyond what's
    visible in the control flow and surrounding code.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [112, 113],  // Useless break comment
    ],
  },
)
