local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 89-94, 96-101, 113-116, 124-132 extract list values into intermediate variables
    (fc1, fco1, fc2, fco2) and immediately use them once in assertions. These single-use
    variables should be inlined directly into the assert_that() calls.

    Variables used exactly once add no semantic clarity and make tests longer. Standard
    pattern: only extract when used multiple times or when the variable name clarifies
    a complex expression. Here fc1/fco1 names don't clarify turn2_input[ri1_idx + 1].

    Note: Lines 19-32 fc1/fc2 definitions are fine - they're used in response sequence
    construction, not single-use assertions.
  |||,
  filesToRanges={
    'adgn/tests/agent/test_reasoning_threading.py': [
      [89, 94],   // fc1 extraction + assertion
      [96, 101],  // fco1 extraction + assertion
      [113, 114], // fc1 extraction + assertion (turn 3)
      [115, 116], // fco1 extraction + assertion (turn 3)
      [124, 129], // fc2 extraction + assertion
      [131, 132], // fco2 extraction + assertion
    ],
  },
)
