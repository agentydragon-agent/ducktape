local I = import '../../specimens/lib.libsonnet';

// Merged: redundant-default-comments, useless-block-comments
// Both describe comments that add no value (redundant or pure noise)

I.issueOneOccurrence(
  rationale= |||
    Multiple locations have comments that add no value: either redundant "Default: no-op"
    statements in hook methods or separator/block comments that serve as visual noise.

    **Pattern 1: Redundant "Default: no-op" comments** (handler.py:132-182):
    ```python
    def on_response(self, evt: Response) -> None:
        """Called after receiving a complete model response with usage stats.

        Default: no-op.
        """
        return

    def on_user_text_event(self, evt: UserText) -> None:
        """Called when user text is added to the conversation.

        Default: no-op.
        """
        return
    ```

    Problems:
    - Implementation already shows `return` (obvious no-op)
    - Base class hooks are conventionally no-ops by design
    - Extra line adds no information
    - Docstring should focus on what the hook does, not what the default does

    Occurs in 6 hook methods: on_response, on_user_text_event, on_assistant_text_event,
    on_tool_call_event, on_tool_result_event, on_reasoning.

    **Pattern 2: Separator and block indicator comments** (cli.py):
    ```python
    # ---------------------------------------------------------------------
    # ---------- constants -------------------------------------------------
    MAX_FILE_LINES = 400

    # Core logic
    def get_short_commitish(repo: pygit2.Repository) -> str:
    ```

    Problems:
    - Separator with no actual section content (line 55)
    - "constants" comment redundant (all-caps naming already indicates constants)
    - "Core logic" is vague and useless (what makes this "core" vs other logic?)
    - Add noise without providing information

    **Why these are problematic:**
    - **Noise**: Make code harder to scan without adding information
    - **Maintenance burden**: Must be kept in sync as code changes
    - **False organization**: Imply structure that doesn't exist
    - **Redundant**: Code already conveys the information

    **Recommended fix:**
    For hook methods: Keep one-line docstrings that explain what the hook does:
    ```python
    def on_response(self, evt: Response) -> None:
        """Called after receiving a complete model response with usage stats."""
        return
    ```

    For block comments: Delete separator lines and vague labels. If grouping is truly
    needed, use blank lines or meaningful section comments that explain WHY, not WHAT.

    **Benefits:**
    - More concise code
    - Focus on what hooks do, not implementation details
    - Less maintenance overhead
    - Standard Python convention (hooks have no-op defaults)
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/handler.py': [
      [132, 137],  // on_response: "Default: no-op"
      [149, 154],  // on_user_text_event: "Default: no-op"
      [156, 161],  // on_assistant_text_event: "Default: no-op"
      [163, 168],  // on_tool_call_event: "Default: no-op"
      [170, 175],  // on_tool_result_event: "Default: no-op"
      [177, 182],  // on_reasoning: "Default: no-op"
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [55, 55],   // "# -------------" - separator with no content
      [58, 58],   // "# ---------- constants" - restates obvious
      [176, 176], // "# Core logic" - vague and useless
      [680, 680], // "# Stage if requested" - restates obvious
      [683, 683], // "# Get previous commit message if amending" - restates obvious
      [687, 687], // "# Check if there's truly nothing to commit" - restates obvious
    ],
  },
)
