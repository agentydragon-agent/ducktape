local I = import '../../specimens/lib.libsonnet';

// iss-023: Inline single-use variable 'tagged'

I.issueOneOccurrence(
  rationale=|||
    Line 200 creates `tagged` variable, which is immediately returned on line 201.
    Single-use variables that don't clarify logic should be inlined.

    **Current:** `tagged = f"..." ; return UserMessage.text(tagged)`
    **Fix:** `return UserMessage.text(f"...")`
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/reducer.py': [
      [200, 201],  // tagged should be inlined into return
    ],
  },
)
