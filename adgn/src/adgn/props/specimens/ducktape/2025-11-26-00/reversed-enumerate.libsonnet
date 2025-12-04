local I = import '../lib.libsonnet';

// iss-017: Use reversed(enumerate(...)) instead of manual reverse iteration

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale= |||
    The `_find_last_tool_index` function manually iterates backwards with `range(..., -1, -1)`
    and a separate line to extract the item. It should use `reversed(enumerate(...))` for
    cleaner, more Pythonic iteration.

    **Current implementation (state.py:110-115):**
    ```python
    def _find_last_tool_index(state: UiState, call_id: str) -> int | None:
        for idx in range(len(state.items) - 1, -1, -1):
            it = state.items[idx]
            if isinstance(it, ToolItem) and it.tool_call.call_id == call_id:
                return idx
        return None
    ```

    **Problems:**
    1. **Manual indexing**: `range(len(...) - 1, -1, -1)` is verbose and error-prone
    2. **Separate item access**: `it = state.items[idx]` requires extra line
    3. **Not idiomatic**: Python provides `reversed(enumerate(...))` for this pattern

    **Correct approach:**
    ```python
    def _find_last_tool_index(state: UiState, call_id: str) -> int | None:
        for idx, it in reversed(list(enumerate(state.items))):
            if isinstance(it, ToolItem) and it.tool_call.call_id == call_id:
                return idx
        return None
    ```

    **Benefits:**
    1. **Pythonic**: Uses standard library pattern for reverse enumeration
    2. **Clearer intent**: "iterate backwards over indexed items" is explicit
    3. **One line per item**: No separate `it = ...` line needed
    4. **Less error-prone**: No manual index arithmetic

    **Note:** Need to wrap `enumerate(...)` in `list()` before `reversed()` because
    `enumerate` returns an iterator that doesn't support reverse iteration directly.

    Alternatively, if performance matters for large lists:
    ```python
    def _find_last_tool_index(state: UiState, call_id: str) -> int | None:
        for i, it in enumerate(reversed(state.items)):
            if isinstance(it, ToolItem) and it.tool_call.call_id == call_id:
                return len(state.items) - 1 - i
        return None
    ```

    But the first version is clearer unless profiling shows performance issues.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/state.py': [
      [110, 115],  // _find_last_tool_index with manual reverse iteration
    ],
  },
)
