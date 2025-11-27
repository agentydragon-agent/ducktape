local I = import '../../specimens/lib.libsonnet';

// Merged: unnecessary-intermediate-vars, intermediate-var-single-use-path, unnecessary-intermediate-boolean, unnecessary-policies-variable
// All describe intermediate variables used only once that should be inlined

I.issueOneOccurrence(
  rationale= |||
    Multiple locations create intermediate variables that are used only once in the
    immediately following statement. These add no clarity and should be inlined.

    **Pattern: Variable assigned and used once**

    **Location 1: cmd and env variables** (runner.py:44-45):
    ```python
    cmd = ["python", "-m", "adgn.agent.policy_eval.shim"]
    env = {"PYTHONUNBUFFERED": "1", "POLICY_SRC": source, "POLICY_INPUT": ctx_json}
    container = containers.create(..., command=cmd, environment=env)
    ```

    **Location 2: Path variable** (cli.py:577-578):
    ```python
    edit_path = Path(repo.path) / "COMMIT_EDITMSG"
    edit_path.write_text(final_text)
    ```

    **Location 3: Boolean variable** (cli.py:592-594):
    ```python
    saved = mtime_after == mtime_before and not changed
    # ...
    if saved:
        # User didn't change anything
    ```

    **Location 4: Query results variable** (sqlite.py:246):
    ```python
    policies = result.scalars().all()
    return [
        # ... comprehension
        for policy in policies
    ]
    ```

    **Problems:**
    - One-off variables add cognitive load
    - No semantic value (names don't add clarity)
    - More lines to read
    - Variable scope is unnecessarily wide

    **Correct approach: Inline directly**

    Location 1:
    ```python
    container = containers.create(
        ...,
        command=["python", "-m", "adgn.agent.policy_eval.shim"],
        environment={"PYTHONUNBUFFERED": "1", "POLICY_SRC": source, "POLICY_INPUT": ctx_json}
    )
    ```

    Location 2:
    ```python
    (Path(repo.path) / "COMMIT_EDITMSG").write_text(final_text)
    ```

    Location 3:
    ```python
    if mtime_after == mtime_before and not changed:
        # User didn't change anything
    ```

    Location 4:
    ```python
    return [
        # ... comprehension
        for policy in result.scalars().all()
    ]
    ```

    **Benefits:**
    - Fewer variables to track
    - More concise code
    - Clearer that value is used once
    - Smaller variable scope
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [
      [44, 45],   // cmd and env intermediate vars
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [577, 578], // edit_path intermediate var
      [592, 594], // saved boolean intermediate var
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [246, 246], // policies query result intermediate var
    ],
  },
)
