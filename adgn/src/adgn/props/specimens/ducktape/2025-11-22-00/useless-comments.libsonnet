local I = import '../../lib.libsonnet';

// Merged: redundant-default-noop-comments, useless-separator-block-comments,
// useless-moved-function-comment, useless-removed-code-comment
// All describe comments that add no value and should be deleted

I.issue(
  rationale= |||
    Comments that add no value: redundant, obvious, historical, or noise.

    **Four categories:**

    **1. Redundant "Default: no-op" docstrings** (handler.py, 6 methods)
    Hook methods with "Default: no-op" in docstrings when implementation is just
    `return`. Base class hooks are conventionally no-ops; stating this is redundant.

    **2. Separator lines and vague labels** (cli.py, 6 locations)
    Empty "# -------" separators, "# constants" restating obvious naming, and vague
    "# Core logic" that adds no information.

    **3. Historical breadcrumbs** (container.py:58)
    Comment noting function was moved. Git history is the source of truth for moves.

    **4. Documenting removed code** (sqlite.py:530-533)
    Four-line block listing old method names that no longer exist. Git commit messages
    should document removals.

    **Problems:** Add cognitive load, become stale, duplicate visible information,
    replace proper documentation (git), obscure valuable comments.

    **Fix:** Delete these comments. Keep only comments explaining non-obvious decisions
    or rationale not visible in code/naming.
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
