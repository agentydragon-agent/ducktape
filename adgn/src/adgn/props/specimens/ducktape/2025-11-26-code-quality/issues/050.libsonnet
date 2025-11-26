local I = import '../../specimens/lib.libsonnet';

// iss-050: Refactor _cap_append - forces callers to think about truncation

I.issueOneOccurrence(
  rationale=|||
    Lines 18-29 define `_cap_append()` which mutates a parts list and handles truncation.
    This forces callers to think about truncation details at each append.

    **Current pattern (lines 133-149):**
    ```python
    parts = []
    parts.append("$ git status --porcelain\n")
    status_out = _format_status_porcelain(repo) + "\n"
    _cap_append(parts, status_out, MAX_PROMPT_CONTEXT_CHARS, "[Context truncated...]")

    parts.append(f"$ {ns_header}\n")
    ns_out = _format_name_status(repo, include_all) + "\n"
    _cap_append(parts, ns_out, MAX_PROMPT_CONTEXT_CHARS, "[Context truncated...]")
    # ... repeated 4 times
    ```

    **Problems:**
    1. Caller must know when to use `_cap_append()` vs `parts.append()`
    2. Truncation logic interleaved with data collection
    3. Same cap (`MAX_PROMPT_CONTEXT_CHARS`) repeated 4 times at call sites
    4. Same truncation note (`"[Context truncated to 100k characters]"`) repeated 4 times
    5. Function mutates list and returns boolean (side effect + return value)
    6. Magic constants duplicated across call sites instead of centralized

    **Better approach:**
    ```python
    # Constants defined once
    MAX_PROMPT_CONTEXT_CHARS = 100_000
    TRUNCATION_NOTE = "[Context truncated to 100k characters]"

    def join_with_truncation(parts: list[str], max_chars: int, note: str) -> str:
        """Join parts, truncating if needed."""
        result = "".join(parts)
        if len(result) > max_chars:
            return result[:max_chars] + note + "\n"
        return result

    # Caller just builds list - no mention of truncation:
    parts = [
        "$ git status --porcelain\n",
        _format_status_porcelain(repo) + "\n",
        f"$ {ns_header}\n",
        _format_name_status(repo, include_all) + "\n",
        # ... etc
    ]
    return join_with_truncation(parts, MAX_PROMPT_CONTEXT_CHARS, TRUNCATION_NOTE)
    ```

    Constants appear once. Truncation happens once at the end.

    **Benefits:**
    1. Caller doesn't think about truncation - just builds list of parts
    2. Truncation happens once at the end
    3. Separation of concerns: data collection vs truncation
    4. Pure function - no mutation
    5. Constants (`MAX_PROMPT_CONTEXT_CHARS`, truncation note) defined once, not repeated
    6. Easy to change truncation behavior in one place

    **Alternative (overengineering):** Use generator/yield pattern as stream processor, but
    that's overkill here. The list-then-truncate approach is simpler and sufficient.

    **Fix:**
    - Delete `_cap_append()` function
    - Add `join_with_truncation()` helper
    - Refactor callers to build full list, then truncate at end
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [18, 29],  // _cap_append - poor abstraction
      [133, 149],  // Caller that interleaves truncation with data collection
    ],
  },
)
