local I = import '../../specimens/lib.libsonnet';

// iss-035: Remove useless comment that duplicates code intent

I.issueOneOccurrence(
  rationale=|||
    Comment states what break statement obviously does (runtime.py:112-113):

    # Break sender loop - connection is broken
    break

    The comment adds no information beyond what "break" already conveys.
    The break is inside an exception handler after logging "WebSocket send failed",
    so context is already clear: connection failed, exit loop.

    Comments should explain *why*, not *what*. This comment just repeats the
    obvious control flow.

    Should remove comment entirely.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [112, 113],   // Useless "Break sender loop" comment
    ],
  },
)
