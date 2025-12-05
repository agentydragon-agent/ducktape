local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 136-147: Complex 12-line assertion with nested loops, boolean flag,
    and break statements should be replaced with declarative hamcrest matcher.

    **What it checks:**
    captured[-1].input contains a UserMessage with content containing InputTextPart
    where text includes "<system notification>".

    **Current approach:** Imperative loops with mutable found flag, manual
    isinstance checks, nested breaks.

    **Should use:** Hamcrest matchers like has_properties, instance_of, and
    contains_string to express the same check declaratively.

    **Benefits:** Declarative vs imperative, no manual loops/flags/breaks, better
    error messages (hamcrest shows diffs), more readable, consistent with other
    tests, eliminates mutable state.
  |||,
  filesToRanges={
    'adgn/tests/agent/test_mcp_notifications_flow.py': [
      [136, 147],  // Complex nested loop assertion
    ],
  },
)
