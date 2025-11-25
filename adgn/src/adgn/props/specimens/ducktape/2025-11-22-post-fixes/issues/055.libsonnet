local I = import '../../specimens/lib.libsonnet';

// iss-055: Useless comment about ModalBackdrop styling

I.issueOneOccurrence(
  rationale= |||
    AgentsSidebar component contains a useless comment about backdrop styling being
    "moved to ModalBackdrop component". This is a historical note that adds no value
    to current readers.

    **Problem: Historical comment with no current value**

    **AgentsSidebar.svelte (line 347):**
    In the `<style>` block, before modal styles:
    ```css
    /* Modal styles */
    /* Backdrop styling moved to ModalBackdrop component */
    .modal { ... }
    ```

    **Why useless:**
    1. **Historical note**: Describes past refactoring, not current behavior
    2. **Obvious from code**: ModalBackdrop component is imported and used in template
    3. **Redundant**: "Modal styles" section header already exists above it
    4. **No action needed**: Not a TODO, not explaining complexity

    Readers don't care that styling was "moved" - they care about current structure.
    The ModalBackdrop component exists and is being used; that's all that matters.

    **Correct approach: Delete the comment**

    ```css
    /* Modal styles */
    .modal { ... }
    ```

    The section header "Modal styles" is sufficient. The fact that ModalBackdrop
    exists is obvious from the imports and usage.

    **When comments ARE useful:**
    - **Explaining suppression**: `// @ts-ignore - library has wrong types`
    - **Complex logic**: `// Binary search, O(log n)`
    - **Workarounds**: `// HACK: IE11 doesn't support X`
    - **TODOs**: `// TODO: refactor when API v2 ships`
    - **Non-obvious behavior**: `// Returns null on weekends`

    **When to delete comments:**
    - **Historical notes**: "moved to...", "used to be...", "changed from..."
    - **Obvious statements**: `// Loop through items`
    - **Redundant markers**: When already clear from structure
    - **Vestigial**: Left from copy-paste, no longer accurate

    This comment is purely historical - it documents a refactoring that already
    happened, provides no insight into current code behavior, and is redundant
    with the existing "Modal styles" section header.
  |||,
  properties=['remove-useless-comments', 'no-historical-notes'],
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[347, 347]],
  },
  gap_note= |||
    This finding illustrates **"no-historical-notes"**: comments should explain
    current behavior, not document past changes. History belongs in git, not comments.

    Principle: Comments explain "why", code explains "what"
    - Good: Why this approach was chosen
    - Bad: What changes were made historically

    Related to **"remove-useless-comments"**: comments that add no information
    should be deleted. Every comment has maintenance cost.

    Why historical comments are harmful:

    **Maintenance burden:**
    - Comment becomes stale as code evolves
    - No one updates "moved from X" when X is deleted
    - Accumulates over time, confusing readers

    **Misdirection:**
    - Reader: "Should I check ModalBackdrop for something?"
    - Actually: Nothing special to check, comment just notes history
    - Wasted time investigating non-issue

    **Clutter:**
    - File full of "moved", "used to", "previously"
    - Signal-to-noise ratio decreases
    - Harder to find actually useful comments

    What to document instead:

    **Current constraints:**
    ```css
    /* Keep modal narrow - wide modals obscure agent list */
    .modal { max-width: 500px; }
    ```

    **Non-obvious behavior:**
    ```css
    /* z-index: 1000 ensures modal appears above sticky headers (z-999) */
    .modal-backdrop { z-index: 1000; }
    ```

    **Workarounds:**
    ```css
    /* Safari doesn't support backdrop-filter, use solid background */
    .modal-backdrop { background: rgba(0,0,0,0.5); }
    ```

    But "moved to ModalBackdrop"? Delete it. Git history records that.

    Red flags for useless comments:
    - Past tense verbs: "moved", "changed", "was", "used to be"
    - No explanation of current behavior
    - Redundant with code structure or names
    - No actionable information

    Good comment litmus test:
    - If I delete this comment, what knowledge is lost?
    - If answer is "none" or "just history", delete it.
  |||,
)
