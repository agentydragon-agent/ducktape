local I = import '../../specimens/lib.libsonnet';

// iss-013: Duplicated git commit invocation across immediate and editor flows

I.issueOneOccurrence(
  rationale= |||
    Both `_commit_immediately()` and `_run_editor_flow()` end by calling `git commit`
    with similar passthru argument handling. The commit logic is duplicated when it
    should be factored out into a shared helper.

    **Current implementation (cli.py, lines 558-615):**
    ```python
    async def _commit_immediately(msg: str, passthru: list[str]) -> int:
        if not msg.strip():
            raise ExitWithCode(1)
        commit_passthru = filter_commit_passthru(passthru)  # ❌ Duplicated
        commit_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", msg, "--no-verify", *commit_passthru  # ❌ Duplicated pattern
        )
        return await commit_proc.wait()  # ❌ Duplicated

    async def _run_editor_flow(...) -> int:
        # ... editor logic: build message, run editor, validate ...
        commit_passthru = filter_commit_passthru(passthru)  # ❌ Duplicated
        commit_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-F", commit_msg_path, "--cleanup=strip", "--no-verify", *commit_passthru  # ❌ Duplicated pattern
        )
        return await commit_proc.wait()  # ❌ Duplicated
    ```

    **Problems:**

    1. **Code duplication**: Both functions create subprocess and handle passthru identically
    2. **Different interfaces**: One uses `-m msg`, other uses `-F path`, but both commit
    3. **Coupled logic**: Both must know about `filter_commit_passthru` and `--no-verify`
    4. **Maintenance burden**: Changes to commit invocation must be duplicated
    5. **Unclear separation**: Functions mix message preparation with commit execution

    **The correct approach:**

    Extract message preparation from commit execution:

    ```python
    async def _prepare_commit_message(
        accept_ai: bool,
        ai_message: str,
        repo: pygit2.Repository,
        previous_message: str | None,
        stats_comment: str,
        passthru: list[str]
    ) -> str:
        \"\"\"Get final commit message, either directly or via editor.\"\"\"
        if accept_ai:
            # Accept AI message directly
            if not ai_message.strip():
                raise ExitWithCode(1, "empty AI commit message")
            return ai_message

        # Run editor flow
        final_text = ai_message
        if previous_message:
            final_text += "\\n\\n# Previous commit message (being amended):\\n"
            for line in previous_message.splitlines():
                final_text += f"# {line}\\n"
        final_text += stats_comment + build_commit_template(repo, passthru)

        commit_msg_path = Path(repo.path) / "COMMIT_EDITMSG"
        commit_msg_path.write_text(final_text)

        editor = await _get_editor()
        editor_proc = await asyncio.create_subprocess_shell(f"{editor} {commit_msg_path}")
        if (rc := await editor_proc.wait()) != 0:
            raise ExitWithCode(1, f"editor exited with code {rc}")

        # ... validation logic ...
        return final_message

    async def _execute_commit(message: str, passthru: list[str]) -> int:
        \"\"\"Execute git commit with the given message.\"\"\"
        commit_passthru = filter_commit_passthru(passthru)
        commit_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message, "--no-verify", *commit_passthru
        )
        return await commit_proc.wait()

    # In async_main():
    final_message = await _prepare_commit_message(
        args.accept_ai, msg, repo, previous_message, stats_comment, passthru
    )
    exit_code = await _execute_commit(final_message, passthru)
    sys.exit(exit_code)
    ```

    **Benefits:**

    1. **Single responsibility**: Each function does one thing
       - `_prepare_commit_message`: Get/validate message (with or without editor)
       - `_execute_commit`: Run git commit subprocess
    2. **No duplication**: Commit logic defined once
    3. **Easier testing**: Can test message preparation separately from commit execution
    4. **Clearer flow**: Main logic shows: prepare message → commit it
    5. **Easier changes**: Modify commit invocation in one place

    **Note:** The exact message passing mechanism (string vs file) can be handled
    inside `_execute_commit` based on message length or other criteria.
  |||,
  properties=['avoid-duplication', 'single-responsibility'],
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [558, 564],  // _commit_immediately: duplicates commit execution
      [611, 615],  // _run_editor_flow: duplicates commit execution
    ],
  },
  gap_note= |||
    This finding illustrates **"single-responsibility"**: functions should do one
    thing. When multiple functions share a common final step (like "execute git commit"),
    that step should be extracted into its own function.

    This is closely related to "avoid-duplication" (DRY), but focuses on the design
    principle: each function should have one reason to change. Here:
    - `_commit_immediately` changes if: message validation OR commit execution changes
    - `_run_editor_flow` changes if: editor logic OR commit execution changes

    After refactoring:
    - `_prepare_commit_message` changes if: message preparation changes
    - `_execute_commit` changes if: commit execution changes

    This makes each function more focused and easier to maintain.
  |||,
)
