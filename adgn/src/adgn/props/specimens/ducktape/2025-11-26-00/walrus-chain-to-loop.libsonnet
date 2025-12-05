local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 687-695 use a chain of walrus operators to check editor candidates. This
    should be refactored into a for-loop for better readability.

    **Current:**
    ```python
    if editor := os.environ.get("GIT_EDITOR"):
        return editor
    if editor := repo.config.get("core.editor"):
        return editor
    if editor := os.environ.get("VISUAL"):
        return editor
    if editor := os.environ.get("EDITOR"):
        return editor
    return "vi"
    ```

    **Refactored:**
    ```python
    for candidate in (
        os.environ.get("GIT_EDITOR"),
        repo.config.get("core.editor"),
        os.environ.get("VISUAL"),
        os.environ.get("EDITOR"),
        "vi",
    ):
        if candidate:
            return candidate
    ```

    **Benefits:**
    1. DRY - no repeated `if editor := ... return editor` pattern
    2. Clear that we're checking candidates in order
    3. Easier to reorder or add/remove candidates
    4. `"vi"` is now part of the candidate list, not special-cased

    **Note:** The loop naturally handles None values (they're falsy and skipped).
    The final "vi" is always truthy so the function always returns.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [687, 695],  // Walrus chain should be for-loop
    ],
  },
)
