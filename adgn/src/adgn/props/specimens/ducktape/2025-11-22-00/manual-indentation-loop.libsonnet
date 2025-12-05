local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Manual loop to indent lines instead of using `textwrap.indent()` from standard library.

    **Current code (cli.py:573-574):**
    ```python
    for line in previous_message.splitlines():
        final_text += f"# {line}\n"
    ```

    **Problems:**
    - Reimplements standard library functionality
    - More verbose than stdlib solution
    - Harder to test independently
    - Potential edge cases not handled (empty lines, trailing newlines)

    **Correct approach:**
    ```python
    final_text += textwrap.indent(previous_message, "# ", lambda line: True)
    ```

    **Benefits:**
    - Uses standard, tested library function
    - More concise (1 line vs 2 lines)
    - Clearer intent (obviously indenting text)
    - Handles edge cases correctly
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [573, 574],  // Manual indentation loop
    ],
  },
)
