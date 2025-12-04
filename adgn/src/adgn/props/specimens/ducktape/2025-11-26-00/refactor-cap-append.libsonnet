local I = import '../../lib.libsonnet';


I.issue(
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
    Replace `_cap_append()` with `join_with_truncation(parts, max_chars, note)` that:
    1. Takes complete list of parts (already built)
    2. Joins all parts with `"".join(parts)`
    3. Truncates once at end if `len(result) > max_chars`
    4. Returns truncated string + note

    Callers build full parts list using plain `list.append()` or list literals, then call
    `join_with_truncation()` once at the end. Constants `MAX_PROMPT_CONTEXT_CHARS` and
    `TRUNCATION_NOTE` defined once at module level, not repeated at call sites.

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
