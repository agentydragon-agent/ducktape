local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The code uses byte length (`_len_bytes()`) to cap context passed to LLMs,
    but LLM token budgets are better approximated by character count, not bytes.

    **Current implementation:**
    Byte-based logic with `_len_bytes()`, `MAX_PROMPT_CONTEXT_BYTES = 100 * 1024`,
    and byte-boundary truncation in `_cap_append()` (lines 14-29). Used to cap
    status, diff, and log output in `_build_ai_context()` (lines 141-166).

    **Problems:**
    1. **Wrong approximation**: LLM tokens correlate with character count, not bytes.
       Multi-byte UTF-8 (emoji/CJK) are 3-4 bytes but typically 1 token, so byte-based
       limits penalize non-ASCII content unnecessarily.
    2. **Arbitrary units**: "100 KiB" is meaningless for token budgets; should be
       expressed as character count or approximate token count.
    3. **Byte-boundary truncation**: Can break mid-character in UTF-8 (code handles
       with `errors="ignore"` but adds complexity).
    4. **Complexity**: Encoding/decoding is more complex than using `len(s)`.

    **Correct approach:**
    Use character count directly. Express cap as `MAX_PROMPT_CONTEXT_CHARS = 100_000`
    (~25k tokens at ~4 chars/token). Truncate via string slicing, which always
    produces valid strings.

    **Benefits:**
    1. Better approximation: Chars correlate with tokens better than bytes
    2. Clearer intent: "100k chars" is more meaningful than "100 KiB"
    3. Simpler code: No encoding/decoding, just string slicing
    4. No mid-character breaks: String slicing always produces valid strings
    5. Portable: Byte lengths vary by encoding; char counts don't

    **Note:** For precise token counting, use a tokenizer (e.g., `tiktoken`). For
    rough caps, character count is a better heuristic than byte length.
  |||,
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
)
