local I = import '../../lib.libsonnet';

// iss-004: Dead code - unused _extract_message_from_text function

I.issue(
  rationale= |||
    The function `_extract_message_from_text()` (lines 260-263) appears to be
    unused dead code. A project-wide search shows:

    **Definition:**
    ```python
    def _extract_message_from_text(text: str) -> str:
        if match := re.search(r"<message>\s*(.*?)\s*</message>", text, re.DOTALL):
            return match.group(1).strip()
        return text.strip()
    ```

    **Usages found:** 0 (only appears in its definition)

    **Context:**

    The function extracts text between `<message>` tags, which suggests it was used
    to parse AI-generated responses that wrapped commit messages in XML tags.

    Looking at the current prompt in `build_prompt()`, the AI is instructed to:
    - "Output ONLY the commit message between <message> and </message> tags"
    - But the backends don't appear to use `_extract_message_from_text()` to parse
      the response

    This suggests either:
    1. The extraction was moved elsewhere and this is leftover code, or
    2. The backends parse the tags directly without using this helper

    **The correct approach:**

    Delete the function. If it's truly unused, keeping it:
    1. **Misleads readers**: Implies this is how messages are extracted
    2. **Clutters the codebase**: Dead code obscures live code
    3. **Maintenance burden**: May get inadvertently "fixed" or updated
    4. **Creates doubt**: Readers wonder if they should be calling it

    If the extraction logic is actually needed somewhere, the deletion will
    cause an import error that makes the dependency explicit.

    **Verification:**

    To confirm it's unused:
    ```bash
    git grep -n '_extract_message_from_text' --
    # Should only show the definition
    ```
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/core.py': [
      [260, 263], // _extract_message_from_text: unused function definition
    ],
  },
)
