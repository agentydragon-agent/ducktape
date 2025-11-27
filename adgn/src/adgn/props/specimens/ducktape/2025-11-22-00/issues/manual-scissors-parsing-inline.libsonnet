local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Complex scissors+comment filtering logic buried inline instead of extracted to
    a reusable helper function.

    **Current code (cli.py:601-609):**
    ```python
    # Manual parsing logic with multiple conditions
    lines = edited_content.splitlines()
    result_lines = []
    for line in lines:
        if line.startswith(scissors_mark):
            break
        if line.startswith("#"):
            continue
        result_lines.append(line)
    final_content = "\n".join(result_lines)
    ```

    This logic is buried inline in the main flow, making it:
    - Hard to read (mix of control flow with scissors parsing)
    - Hard to test (can't test scissors parsing independently)
    - Not reusable (if needed elsewhere, must duplicate)
    - Clutters main function logic

    **Correct approach:**

    Extract to helper function:
    ```python
    def extract_commit_content(text: str, scissors_mark: str) -> str:
        """Extract commit message content, removing scissors line and comments."""
        result_lines = []
        for line in text.splitlines():
            if line.startswith(scissors_mark):
                break
            if line.startswith("#"):
                continue
            result_lines.append(line)
        return "\n".join(result_lines)

    # Main function
    final_content = extract_commit_content(edited_content, scissors_mark)
    ```

    **Benefits:**
    - Single responsibility (helper does one thing)
    - Testable independently
    - Reusable
    - Main function logic is clearer
    - Can document edge cases in helper docstring
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [601, 609],  // Manual scissors+comment parsing
    ],
  },
)
