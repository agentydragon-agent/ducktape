local I = import '../../specimens/lib.libsonnet';

// iss-014: Multiple simplification opportunities in _run_editor_flow

I.issueOneOccurrence(
  rationale= |||
    The `_run_editor_flow` function contains several patterns that could be simplified
    using standard library utilities, more concise expressions, and better abstractions.

    **Issue 1: Manual indentation instead of textwrap.indent (lines 573-574):**
    ```python
    # Current:
    for line in previous_message.splitlines():
        final_text += f"# {line}\n"

    # Better:
    import textwrap
    final_text += textwrap.indent(previous_message, "# ", lambda line: True)
    ```

    **Issue 2: Intermediate variable for Path construction (lines 577-578):**
    ```python
    # Current:
    commit_msg_path = Path(repo.path) / "COMMIT_EDITMSG"
    commit_msg_path.write_text(final_text)

    # Better (one-liner):
    (Path(repo.path) / "COMMIT_EDITMSG").write_text(final_text)
    # Or keep reference if used multiple times below
    ```

    **Issue 3: Needless variable rename (line 581):**
    ```python
    # Current:
    final_text = msg
    # ... build up final_text ...
    content_before = final_text  # Unnecessary rename

    # Better:
    content_before = msg
    # ... build up content_before ...
    # Just use "content_before" from the start
    ```

    **Issue 4: Unnecessary intermediate boolean (lines 592-594):**
    ```python
    # Current:
    saved = mtime_after != mtime_before
    changed = final_content.rstrip("\n") != content_before
    if not saved and not changed:
        raise ExitWithCode(1)

    # Better (inline the simple check):
    changed = final_content.rstrip("\n") != content_before
    if mtime_after == mtime_before and not changed:
        raise ExitWithCode(1)
    ```

    **Issue 5: Manual line parsing instead of scissors extraction (lines 601-609):**
    ```python
    # Current:
    content_lines: list[str] = []
    for line in final_content.splitlines():
        if line.startswith(SCISSORS_MARK):
            break
        if line.strip() and not line.strip().startswith("#"):
            content_lines.append(line)
    if not content_lines:
        raise ExitWithCode(1)

    # Better:
    def extract_commit_content(text: str, scissors_mark: str) -> str:
        """Extract commit message content, stopping at scissors and removing comments."""
        lines = text.splitlines()
        try:
            scissors_index = next(i for i, line in enumerate(lines) if line.startswith(scissors_mark))
            lines = lines[:scissors_index]
        except StopIteration:
            pass  # No scissors mark found, use all lines

        content_lines = [
            line for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        return "\n".join(content_lines)

    # Usage:
    content = extract_commit_content(final_content, SCISSORS_MARK)
    if not content:
        raise ExitWithCode(1)
    ```

    **Problems with current code:**

    1. **Reimplements stdlib**: Manual indentation loop instead of `textwrap.indent`
    2. **Unnecessary variables**: `saved` boolean and `content_before` rename add no clarity
    3. **Missing abstraction**: Scissors+comment parsing is complex logic buried inline
    4. **Less readable**: Manual loop with multiple conditions harder to understand than
       declarative list comprehension
    5. **Not reusable**: Scissors parsing logic can't be tested or reused independently

    **Benefits of refactoring:**

    1. **Standard library**: Use `textwrap.indent` for indentation (standard, tested, clear)
    2. **Fewer variables**: Less cognitive load, fewer names to track
    3. **Single responsibility**: Extract scissors parsing into testable function
    4. **More declarative**: Comprehensions and utilities express intent clearly
    5. **Easier to test**: Extracted function can be unit tested with various inputs
    6. **More maintainable**: Changing scissors logic happens in one place

    **Note on textwrap.indent:**
    ```python
    import textwrap
    # indent(text, prefix, predicate=None)
    # If predicate is None, only non-empty lines are indented
    # Pass lambda: True to indent all lines including empty ones
    textwrap.indent(previous_message, "# ", lambda line: True)
    ```
  |||,
  properties=['use-stdlib', 'extract-helper', 'remove-noise'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [573, 574],  // Manual indentation loop
      [577, 578],  // Could be one-liner
      [581, 581],  // Needless rename of final_text to content_before
      [592, 594],  // Unnecessary "saved" boolean variable
      [601, 609],  // Manual scissors+comment parsing
    ],
  },
  gap_note= |||
    This finding illustrates **"use-stdlib"**: prefer standard library utilities over
    manual reimplementation. Python's standard library provides well-tested, optimized
    implementations for common patterns.

    Examples from this code:
    - `textwrap.indent()` for adding prefixes to lines
    - `str.removeprefix()` / `str.removesuffix()` for string trimming (Python 3.9+)
    - `itertools` for complex iteration patterns
    - `pathlib.Path` for file operations (already used, good)

    Related to "extract-helper": when standard library doesn't provide the exact
    utility you need (like scissors parsing), extract it into a named, testable helper
    rather than keeping complex logic inline.

    Related to "remove-noise": unnecessary intermediate variables (like `saved` when
    only used once, or `content_before` as a rename) add cognitive load without value.
  |||,
)
