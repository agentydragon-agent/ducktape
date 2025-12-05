local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 110-115 define `_find_last_tool_index()` which manually iterates backwards using
    `range(len(state.items) - 1, -1, -1)` and a separate line to extract each item. This
    is verbose and error-prone.

    **Problems:**
    Manual index arithmetic (`len(...) - 1, -1, -1`) is verbose. Separate item access
    (`it = state.items[idx]`) adds an extra line. This pattern has a standard Python idiom:
    `reversed(enumerate(...))`.

    **Fix:** Use `for idx, it in reversed(list(enumerate(state.items)))`. This makes intent
    explicit ("iterate backwards over indexed items"), eliminates manual arithmetic, and
    combines index+item access in one line.

    Note: wrap `enumerate(...)` in `list()` before `reversed()` because enumerate returns
    an iterator that doesn't support reverse iteration directly.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [
      [110, 115],  // _find_last_tool_index with manual reverse iteration
    ],
  },
)
