local I = import '../../specimens/lib.libsonnet';

// iss-042: Should inline md variable in UiState construction

I.issueOneOccurrence(
  rationale=|||
    Code creates intermediate variable md, used once immediately (reducer.py:60-61):

    md = evt.message.content
    return UiState(seq=state.seq + 1, items=[*state.items, AssistantMarkdownItem(md=md)])

    Should inline:
    return UiState(
        seq=state.seq + 1,
        items=[*state.items, AssistantMarkdownItem(md=evt.message.content)]
    )

    Benefits:
    - Less code: removes intermediate variable
    - Clearer: transformation visible at use site
    - Standard pattern: inline single-use property access

    The variable has no semantic value and isn't referenced elsewhere.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'adgn/src/adgn/agent/server/reducer.py': [
      [60, 61],     // md variable and immediate use
    ],
  },
)
