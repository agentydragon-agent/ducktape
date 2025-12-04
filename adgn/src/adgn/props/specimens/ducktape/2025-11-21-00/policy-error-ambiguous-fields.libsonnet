local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 23-24 define `index` and `length` fields in `PolicyError` with ambiguous descriptions:
    "Character/token index where error occurred" and "Length of error span in characters/tokens".

    The descriptions don't specify whether values are character indices or token indices. Is
    `index=10` the 10th character or 10th token? How does the consumer know which? No way to
    distinguish makes the fields meaningless. Same problem for `length=5` (five characters or
    five tokens?).

    There's no evidence these fields are populated or consumed anywhere in the codebase. They
    provide unnecessary detail. Different error sources might use different interpretations,
    making the fields inconsistent and unreliable.

    Remove both fields. The existing `message` field can include location details when needed
    (e.g., "Parse error at line 5, column 10"). Benefits: eliminates unusable ambiguous fields,
    simpler model, clearer focus on stage/code/message.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/models/policy_error.py': [
      [23, 24],  // Ambiguous index and length fields
    ],
  },
)
