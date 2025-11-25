local I = import '../../specimens/lib.libsonnet';

// iss-006: Useless comments that add no value

I.issueOneOccurrence(
  rationale= |||
    Several comments in the code add no value beyond what the code itself conveys.
    They serve as "block indicators" or restate what's obvious from the code structure.

    **Examples:**

    **Line 55:**
    ```python
    from .core import _diff, _format_status_porcelain, include_all_from_passthru
    from .editor_template import SCISSORS_MARK, build_commit_template

    # ---------------------------------------------------------------------
    ```
    A separator comment with no actual section content. Pure visual noise.

    **Line 58:**
    ```python
    # ---------- constants -------------------------------------------------
    MAX_FILE_LINES = 400
    ```
    Comment "# ---------- constants" is redundant - the all-caps naming already
    indicates these are constants. The dashed line adds no information.

    **Line 176:**
    ```python
    # Core logic
    def get_short_commitish(repo: pygit2.Repository) -> str:
    ```
    Comment "# Core logic" is vague and useless. What makes this "core" vs other
    logic? The comment adds nothing.

    **Why these are problematic:**

    1. **Noise**: Comments should explain *why*, not restate *what*
    2. **Maintenance burden**: Must be kept in sync as code changes
    3. **False organization**: Imply a structure that doesn't exist
       (one import ≠ a "section")
    4. **Clutter**: Make it harder to scan the actual imports

    **The correct approach:**

    Delete these comments. Good imports are self-documenting:
    ```python
    from .core import _diff, _format_status_porcelain, include_all_from_passthru
    from .editor_template import SCISSORS_MARK, build_commit_template
    from .anthropic_backend import generate_commit_message_anthropic
    from .minicodex_backend import generate_commit_message_minicodex
    from .config import AppConfig
    ```

    If grouping is truly needed, use blank lines:
    ```python
    # Core utilities
    from .core import _diff, _format_status_porcelain, include_all_from_passthru

    # Backend implementations
    from .anthropic_backend import generate_commit_message_anthropic
    from .minicodex_backend import generate_commit_message_minicodex
    ```

    **When comments ARE useful:**
    - Explaining *why* an unusual import order is needed
    - Noting workarounds for import cycles
    - Explaining conditional imports (`if TYPE_CHECKING:`)

    **Contrast with good comments:**
    ```python
    # Import llama_cpp only if available; falls back to OpenAI
    try:
        from llama_cpp import Llama
    except ImportError:
        Llama = None
    ```
  |||,
  properties=['meaningful-comments', 'remove-noise'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [55, 55],   // "# -------------" - separator with no content
      [58, 58],   // "# ---------- constants" - restates obvious
      [176, 176], // "# Core logic" - vague and useless
      [680, 680], // "# Stage if requested" - restates obvious
      [683, 683], // "# Get previous commit message if amending" - restates obvious
      [687, 687], // "# Check if there's truly nothing to commit" - restates obvious
    ],
  },
  gap_note= |||
    This finding illustrates **"meaningful-comments"**: comments should add
    information that isn't obvious from the code itself.

    Good comments explain:
    - Why (rationale for decisions)
    - How (complex algorithms)
    - What not to do (gotchas, pitfalls)
    - Context (historical reasons, external constraints)

    Bad comments:
    - Restate what the code does
    - Label obvious sections
    - Repeat information from names/types
    - State the obvious

    Related to "remove-noise": every line in a file competes for attention.
    Useless comments are worse than no comments because they train readers
    to ignore all comments.
  |||,
)
