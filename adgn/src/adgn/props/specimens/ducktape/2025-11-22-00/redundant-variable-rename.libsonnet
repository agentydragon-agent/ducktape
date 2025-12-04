local I = import '../../lib.libsonnet';

// Merged: redundant-variable-rename, needless-variable-rename
// Both describe unnecessary variable renames that add no clarity

I.issue(
  rationale= |||
    Variables are renamed without adding clarity or semantic meaning. Either use
    the semantic name from the start, or keep the original name.

    **Location 1: client = docker_client** (runner.py:32):
    ```python
    def run_policy_source(docker_client, ...):
        client = docker_client  # Line 32: pointless rename
        # ... use client throughout
    ```

    The parameter `docker_client` is immediately renamed to `client`. This adds
    no value - just use the parameter name directly throughout the function, or
    name the parameter `client` from the start.

    **Location 2: content_before = final_text** (cli.py:581):
    ```python
    final_text = ...  # Build final text
    # ...
    content_before = final_text  # Line 581: rename
    ```

    Variable `final_text` is renamed to `content_before`, but both names mean the
    same thing (the text before the editor runs). Use the semantic name from the
    beginning if it's clearer.

    **Problems with needless renames:**
    - Extra variables to track
    - Confusion about which name to use
    - No added clarity or semantic value
    - More lines of code
    - Cognitive load (reader must remember alias)

    **Correct approach:**

    Location 1: Either rename parameter to `client` or use `docker_client` throughout:
    ```python
    def run_policy_source(client, ...):  # Rename parameter
        # ... use client directly
    ```
    Or:
    ```python
    def run_policy_source(docker_client, ...):  # Keep parameter name
        # ... use docker_client throughout (remove client assignment)
    ```

    Location 2: Use `content_before` from the start if that's the semantic name:
    ```python
    content_before = ...  # Build text before editor
    # No rename needed
    ```

    **Benefits:**
    - Fewer variables
    - No confusion about naming
    - Clearer intent
    - Less code
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [
      [32, 32],  // client = docker_client
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [581, 581], // content_before = final_text
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/policy_eval/runner.py'],
    ['adgn/src/adgn/git_commit_ai/cli.py'],
  ],
)
