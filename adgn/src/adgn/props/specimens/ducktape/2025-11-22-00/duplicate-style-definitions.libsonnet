local I = import '../../lib.libsonnet';


I.issue(
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
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte': [[347, 347]],
  },
)
