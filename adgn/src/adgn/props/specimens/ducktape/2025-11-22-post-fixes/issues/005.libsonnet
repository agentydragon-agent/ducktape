local I = import '../../specimens/lib.libsonnet';

// iss-005: Using byte length for LLM token budget instead of character count

I.issueOneOccurrence(
  rationale= |||
    The code uses byte length (`_len_bytes()`) to cap context passed to LLMs,
    but LLM token budgets are better approximated by character count, not bytes.

    **Current implementation (core.py, lines 14-29):**
    ```python
    MAX_PROMPT_CONTEXT_BYTES = 100 * 1024  # 100 KiB cap for AI context block

    def _len_bytes(s: str) -> int:
        return len(s.encode("utf-8"))

    def _cap_append(parts: list[str], chunk: str, cap_bytes: int, truncation_note: str) -> bool:
        """Append chunk to parts unless this would exceed cap; returns True if truncated."""
        current_bytes = _len_bytes("".join(parts))
        needed_bytes = _len_bytes(chunk)
        if current_bytes + needed_bytes >= cap_bytes:
            # ... truncate based on byte boundaries
    ```

    **Used in:**
    - `_build_ai_context()` - capping status, diff, and log output (lines 141-166)

    **Problems:**

    1. **Wrong approximation**: LLM tokens correlate with character count, not bytes
       - ASCII characters: 1 byte = 1 char (reasonable)
       - Multi-byte UTF-8: e.g., emoji/CJK are 3-4 bytes but typically 1 token
       - Byte-based limit penalizes non-ASCII content unnecessarily

    2. **Arbitrary units**: "100 KiB" is meaningless for token budgets
       - Should be expressed as character count or approximate token count
       - Makes it harder to reason about actual LLM capacity

    3. **Byte-boundary truncation**: Truncating at byte boundaries can break
       mid-character in UTF-8, though the code handles this with `errors="ignore"`

    4. **Complexity**: Converting to bytes, measuring, truncating, converting back
       is more complex than just using `len(s)`

    **The correct approach:**

    Use character count directly:

    ```python
    MAX_PROMPT_CONTEXT_CHARS = 100_000  # ~25k tokens at ~4 chars/token

    def _cap_append(parts: list[str], chunk: str, cap_chars: int, truncation_note: str) -> bool:
        current_chars = len("".join(parts))
        needed_chars = len(chunk)
        if current_chars + needed_chars >= cap_chars:
            remaining_chars = cap_chars - current_chars
            if remaining_chars > 0:
                parts.append(chunk[:remaining_chars])
            parts.append(truncation_note + "\n")
            return True
        parts.append(chunk)
        return False
    ```

    **Benefits:**

    1. **Better approximation**: Chars correlate with tokens better than bytes
    2. **Clearer intent**: "100k chars" is more meaningful than "100 KiB"
    3. **Simpler code**: No encoding/decoding, just string slicing
    4. **No mid-character breaks**: String slicing always produces valid strings
    5. **Portable**: Byte lengths vary by encoding; char counts don't

    **Note on token estimation:**

    For precise token counting, use a tokenizer (e.g., `tiktoken`). But for
    rough caps, character count is a better heuristic than byte length.
    Typical ratio: 1 token ≈ 4 chars for English text.
  |||,
  properties=['appropriate-abstractions', 'simplicity'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [8, 8],     // MAX_PROMPT_CONTEXT_BYTES constant (wrong unit)
      [14, 15],   // _len_bytes: unnecessary helper
      [18, 29],   // _cap_append: byte-based truncation logic
      [146, 146], // _build_ai_context: status capping with bytes
      [151, 151], // _build_ai_context: name-status capping with bytes
      [155, 155], // _build_ai_context: log capping with bytes
      [160, 160], // _build_ai_context: diff capping with bytes
      [163, 165], // _build_ai_context: final byte-based truncation
    ],
  },
  gap_note= |||
    This finding illustrates **"appropriate-abstractions"**: when modeling a
    constraint (LLM token budget), use units that match the domain.

    - Bytes are appropriate for: file I/O, network transfer, memory allocation
    - Characters are appropriate for: text processing, LLM token estimation
    - Tokens are appropriate for: precise LLM budget tracking (requires tokenizer)

    Choosing the wrong unit adds complexity (encoding/decoding) and reduces
    accuracy (multi-byte UTF-8 skews the estimate).

    Related to "simplicity": the simpler implementation (character counting) is
    also more correct for this use case.
  |||,
)
