local I = import '../../lib.libsonnet';

// Merged: archaeology-comment, trivial-amend-detection-comment,
// trivial-build-status-comment, trivial-print-comment
// All describe comments that add no value and should be deleted

I.issue(
  rationale= |||
    Comments that add no value: obvious narration, historical notes, or trivial restatements
    of what code already shows. Good comments explain non-obvious decisions; these should
    be deleted.

    **Four categories of useless comments in cli.py:**

    **1. Historical/archaeology comment (line 873)**
    "Factor out task creation to a single place" - carries historical intent rather than
    present-tense information. The refactoring already happened; comment is archaeology.

    **2. Trivial narration comments (lines 772, 686-687, 694-695)**
    Three comments that merely restate the next line without adding context:
    - "Detect --amend flag" → next line checks for --amend
    - "Build status string" → next line constructs status string
    - "Print the status" → next line prints output

    The code itself is self-explanatory. Narration comments add noise without information.

    **Problems with useless comments:**
    - Add cognitive load when scanning code
    - State the obvious (what code already shows)
    - Historical comments become stale/misleading
    - Make it harder to find valuable comments

    **Correct approach: Delete useless comments**

    Comments should explain non-obvious decisions, edge cases, or rationale not visible
    in code. Delete comments that:
    - Restate what code/naming already shows
    - Carry historical intent (use git history)
    - Are trivial narration of next line
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [
      [873, 873],    // Historical archaeology comment
      [772, 772],    // Trivial narration: "Detect --amend flag"
      [686, 687],    // Trivial narration: "Build status string"
      [694, 695],    // Trivial narration: "Print the status"
    ],
  },
)
