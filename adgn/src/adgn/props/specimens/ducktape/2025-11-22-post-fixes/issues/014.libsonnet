local I = import '../../specimens/lib.libsonnet';

// iss-014: Multiple simplification opportunities in _run_editor_flow

I.issueOneOccurrence(
  rationale= |||
    The `_run_editor_flow` function contains several patterns that could be simplified
    using standard library utilities, more concise expressions, and better abstractions.

    **Issue 1: Manual indentation loop (lines 573-574):**
    Replace `for line in previous_message.splitlines(): final_text += f"# {line}\n"`
    with `textwrap.indent(previous_message, "# ", lambda line: True)`.

    **Issue 2: Intermediate variable for Path (lines 577-578):**
    Can inline to `(Path(repo.path) / "COMMIT_EDITMSG").write_text(final_text)` if
    path is only used once, or keep reference if used multiple times.

    **Issue 3: Needless variable rename (line 581):**
    Variable `final_text` is renamed to `content_before` without adding clarity; use
    the semantic name from the start.

    **Issue 4: Unnecessary intermediate boolean (lines 592-594):**
    The `saved` boolean is only used once; inline the mtime comparison directly in the
    condition: `if mtime_after == mtime_before and not changed:`.

    **Issue 5: Manual scissors parsing (lines 601-609):**
    Extract scissors+comment filtering into a helper function `extract_commit_content(text,
    scissors_mark)` that returns the cleaned string. Current inline loop with multiple
    conditions is harder to read/test than a named, reusable helper.

    **Problems:**

    1. **Reimplements stdlib**: Manual indentation instead of `textwrap.indent`
    2. **Unnecessary variables**: Single-use booleans and renames add cognitive load
    3. **Missing abstraction**: Complex scissors parsing logic buried inline
    4. **Not reusable**: Scissors parsing can't be tested independently

    **Benefits of refactoring:**

    1. **Use stdlib**: `textwrap.indent` is standard, tested, clear
    2. **Fewer variables**: Less cognitive load
    3. **Single responsibility**: Extract scissors parsing into testable function
    4. **More maintainable**: Changing scissors logic happens in one place
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [573, 574],  // Manual indentation loop
      [577, 578],  // Could be one-liner
      [581, 581],  // Needless rename of final_text to content_before
      [592, 594],  // Unnecessary "saved" boolean variable
      [601, 609],  // Manual scissors+comment parsing
    ],
  },
)
