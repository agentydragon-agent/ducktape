local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 14-15 define `_len_chars(s: str) -> int` which just returns `len(s)`. This
    is a trivial wrapper that should be deleted.

    **Current:**
    ```python
    def _len_chars(s: str) -> int:
        return len(s)

    # Used at:
    current_chars = sum(_len_chars(p) for p in parts)  # line 20
    needed_chars = _len_chars(chunk)  # line 21
    if _len_chars(out) > MAX_PROMPT_CONTEXT_CHARS:  # line 152
    ```

    **Fix:**
    - Delete lines 14-15
    - Line 20: Use `len(p)` instead of `_len_chars(p)`
    - Line 21: Use `len(chunk)` instead of `_len_chars(chunk)`
    - Line 152: Use `len(out)` instead of `_len_chars(out)`

    **Benefits:**
    1. Fewer functions
    2. Uses standard library directly
    3. No indirection

    **Note:** This function was likely created thinking strings might be measured differently
    than their length, but Python's `len()` on strings returns character count, which is
    what we want.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [14, 15],  // Trivial wrapper - delete
      20,  // Use len(p)
      21,  // Use len(chunk)
      152,  // Use len(out)
    ],
  },
)
