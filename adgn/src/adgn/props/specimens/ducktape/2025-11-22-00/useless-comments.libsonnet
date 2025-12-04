local I = import '../../lib.libsonnet';

// Merged: redundant-default-noop-comments, useless-separator-block-comments,
// useless-moved-function-comment, useless-removed-code-comment
// All describe comments that add no value and should be deleted

I.issue(
  rationale= |||
    Comments that add no value: redundant, obvious, historical breadcrumbs, or noise.
    Good comments explain non-obvious decisions; these comments should be deleted.

    **Four categories of useless comments:**

    **1. Redundant "Default: no-op" docstrings (handler.py)**
    Six hook methods have "Default: no-op" in docstrings when implementation shows
    `return` (obviously a no-op). Base class hooks are conventionally no-ops by design.
    Keep the one-line explanation of what the hook does, delete the redundant statement.

    **2. Separator lines and vague section labels (cli.py)**
    Six locations with useless separators and obvious/vague labels:
    - "# -------------" separator with no section content
    - "# ---------- constants" restates what all-caps naming already shows
    - "# Core logic" is vague, adds no information
    - Comments that merely restate following code

    **3. Historical breadcrumbs about moved functions (container.py)**
    Comment noting `run_policy_source` was moved to another module. Git history is the
    source of truth for when/where functions moved. Use `git log`/`git blame` instead
    of leaving stale breadcrumbs.

    **4. Documenting removed code (sqlite.py)**
    Four-line comment block listing old method names that no longer exist. Git commit
    messages should document what was removed and why. Comments about historical removals
    add noise without actionable information.

    **Problems with useless comments:**
    - Add cognitive load when scanning code
    - Become stale as code evolves (wrong/outdated information)
    - Duplicate what's already visible (code structure, naming, implementation)
    - Replace proper documentation (git history, commit messages)
    - Make it harder to find valuable comments

    **Correct approach: Delete useless comments**

    Comments should explain non-obvious decisions, edge cases, or rationale not visible
    in code. Delete comments that:
    - Restate what code/naming already shows
    - Are vague section labels with no specific guidance
    - Track historical changes (use git history)
    - Are separator lines for visual grouping
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/handler.py': [
      [132, 137],  // on_response: "Default: no-op" comment
      [149, 154],  // on_user_text_event: "Default: no-op" comment
      [156, 161],  // on_assistant_text_event: "Default: no-op" comment
      [163, 168],  // on_tool_call_event: "Default: no-op" comment
      [170, 175],  // on_tool_result_event: "Default: no-op" comment
      [177, 182],  // on_reasoning: "Default: no-op" comment
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [55, 55],    // Useless separator line
      [58, 58],    // "# ---------- constants" restates obvious
      [176, 176],  // "# Core logic" vague label
      [680, 680],  // Comment restating code
      [683, 683],  // Comment restating code
      [687, 687],  // Comment restating code
    ],
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [58, 58],    // Historical breadcrumb about moved function
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [530, 533],  // Four-line block documenting removed code
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/handler.py'],
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/agent/policy_eval/container.py'],
    ['adgn/src/adgn/agent/persist/sqlite.py'],
  ],
)
