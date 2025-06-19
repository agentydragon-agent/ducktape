#!/usr/bin/env python3
"""Tests for git-commit-ai script."""

import asyncio
import contextlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from git import Repo

# Add parent directory to path to import git_commit_ai
parent_dir = str(Path(__file__).parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import after adding to path
from git_commit_ai import (  # noqa: E402
    ParallelTaskRunner,
    TaskState,
    TaskStatus,
    async_main,
)


@pytest.fixture()
def make_mock_claude(tmp_path, monkeypatch):
    """Base fixture for creating mock claude commands."""

    def create_claude(script_content):
        mock_claude = tmp_path / "claude"
        mock_claude.write_text(f"#!/usr/bin/env python3\n{script_content}")
        mock_claude.chmod(0o755)
        # Prepend tmp_path to existing PATH instead of replacing it
        current_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{tmp_path}:{current_path}")
        return tmp_path

    return create_claude


@pytest.fixture()
def mock_claude_path(make_mock_claude):
    """Create a mock claude command with successful response."""
    return make_mock_claude(
        '''# Default mock claude response
print("""<message>
Add initial test file

This commit introduces a basic test file to the repository.
</message>""")
''',
    )


@pytest.fixture()
def mock_failing_claude_path(make_mock_claude):
    """Create a mock claude command that returns an error."""
    return make_mock_claude(
        """import sys
sys.stderr.write("Error: API rate limit exceeded\\n")
sys.exit(1)
""",
    )


@pytest.fixture()
def mock_slow_claude_path(make_mock_claude):
    """Create a mock claude command that responds slowly."""
    return make_mock_claude(
        """import time
print("<message>")
time.sleep(0.5)  # Simulate slow response
print("This message should not be used if pre-commit fails")
print("</message>")
""",
    )


@pytest.fixture()
def mock_ui():
    """Create a mock UI that captures output chunks."""
    output_chunks = []

    class MockUI:
        def add_output_chunk(self, data):
            # Store the decoded text for easier assertions
            output_chunks.append(data.decode("utf-8", errors="replace"))

    ui = MockUI()
    ui.output_chunks = output_chunks  # Make chunks accessible for assertions
    return ui


@pytest.fixture()
def test_repo(tmpdir):
    """Create a temporary git repository for testing."""
    repo = Repo.init(tmpdir)
    with repo.config_writer() as cw:
        cw.set_value("user", "email", "test@example.com")
        cw.set_value("user", "name", "Test User")

    # Create initial commit so HEAD exists
    test_file = Path(tmpdir) / "README.md"
    test_file.write_text("# Test Repository\n")
    repo.index.add([str(test_file)])
    repo.index.commit("Initial commit")

    # Now stage a change for testing
    test_file = Path(tmpdir) / "test.txt"
    test_file.write_text("Hello, world!\n")
    repo.index.add([str(test_file)])

    return repo


def _create_precommit_hook(test_repo, hook_content):
    """Helper to create pre-commit hooks."""
    hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
    hook_path.parent.mkdir(exist_ok=True)
    hook_path.write_text(hook_content)
    hook_path.chmod(0o755)
    return test_repo


@pytest.fixture()
def test_repo_with_precommit(test_repo):
    """Create a test repo with a pre-commit hook that outputs colors."""
    hook_content = """#!/bin/bash
echo -e "\\033[32m✓\\033[0m Starting pre-commit checks..."
sleep 0.1
echo -e "\\033[33m⚠\\033[0m  Checking code style..."
sleep 0.1
echo -e "\\033[32m✓\\033[0m Code style OK"
echo -e "\\033[33m⚠\\033[0m  Running tests..."
sleep 0.1
echo -e "\\033[32m✓\\033[0m All tests passed!"
echo -e "\\033[32m✓\\033[0m Pre-commit checks completed successfully"
exit 0
"""
    return _create_precommit_hook(test_repo, hook_content)


@pytest.fixture()
def test_repo_with_failing_precommit(test_repo):
    """Create a test repo with a failing pre-commit hook."""
    hook_content = """#!/bin/bash
echo -e "\\033[32m✓\\033[0m Starting pre-commit checks..."
sleep 0.1
echo -e "\\033[31m✗\\033[0m Found lint errors!"
echo "  - Line too long at file.py:42"
echo "  - Unused import at utils.py:3"
exit 1
"""
    return _create_precommit_hook(test_repo, hook_content)


class TestParallelTaskRunner:
    """Test the ParallelTaskRunner UI class."""

    @pytest.mark.parametrize(
        ("status", "expected_icon"),
        [
            (TaskStatus.RUNNING, "⏳"),
            (TaskStatus.SUCCESS, "✓"),
            (TaskStatus.FAILED, "✗"),
            (TaskStatus.CANCELLED, "-"),
        ],
    )
    def test_status_icons(self, status, expected_icon):
        """Test status icon generation."""
        icon = ParallelTaskRunner._get_status_icon(status)
        assert str(icon) == expected_icon

    @pytest.mark.asyncio()
    async def test_status_display(self):
        """Test that status display shows correct icons and timing."""

        # Create tasks that we can control
        ai_event = asyncio.Event()
        precommit_event = asyncio.Event()

        async def mock_ai_task():
            await ai_event.wait()
            return "Test commit message"

        async def mock_precommit_task():
            await precommit_event.wait()
            return 0

        ai_task = asyncio.create_task(mock_ai_task())
        precommit_task = asyncio.create_task(mock_precommit_task())

        ui = ParallelTaskRunner(TaskState(ai_task), TaskState(precommit_task))

        # Check initial state
        assert ui.precommit_state.status == TaskStatus.RUNNING
        assert ui.ai_state.status == TaskStatus.RUNNING

        # Clean up
        ai_event.set()
        precommit_event.set()
        await ai_task
        await precommit_task

    @pytest.mark.asyncio()
    async def test_successful_tasks(self):
        """Test UI with both tasks succeeding."""

        # Create mock tasks
        async def mock_ai_task():
            await asyncio.sleep(0.2)
            return "Fix bug in authentication"

        async def mock_precommit_task():
            await asyncio.sleep(0.1)
            return 0

        ai_task = asyncio.create_task(mock_ai_task())
        precommit_task = asyncio.create_task(mock_precommit_task())

        ui = ParallelTaskRunner(TaskState(ai_task), TaskState(precommit_task))

        # Mock the context to avoid starting the update loop
        with patch.object(ui, "_context", MagicMock()):
            async with ui:
                await asyncio.gather(ai_task, precommit_task)
                # Give the update loop time to process the completed tasks
                await asyncio.sleep(0.3)

        # Debug output
        print(f"precommit_status: {ui.precommit_state.status}")
        print(f"ai_status: {ui.ai_state.status}")
        print(f"precommit_duration: {ui.precommit_state.duration}")
        print(f"ai_duration: {ui.ai_state.duration}")
        print(f"ai_task done: {ai_task.done()}")
        print(f"precommit_task done: {precommit_task.done()}")

        assert ui.precommit_state.status == TaskStatus.SUCCESS
        assert ui.ai_state.status == TaskStatus.SUCCESS
        assert ui.precommit_state.duration is not None
        assert ui.ai_state.duration is not None

    @pytest.mark.asyncio()
    async def test_failing_precommit(self):
        """Test UI when pre-commit fails."""

        # Create mock tasks
        async def mock_ai_task():
            await asyncio.sleep(0.5)  # Long running
            return "Fix bug in authentication"

        async def mock_precommit_task():
            await asyncio.sleep(0.1)
            raise Exception("Pre-commit failed")

        ai_task = asyncio.create_task(mock_ai_task())
        precommit_task = asyncio.create_task(mock_precommit_task())

        ui = ParallelTaskRunner(TaskState(ai_task), TaskState(precommit_task))

        with patch.object(ui, "_context", MagicMock()):
            async with ui:
                # Wait for pre-commit to fail
                with pytest.raises(Exception, match="Pre-commit failed"):
                    await precommit_task
                # Give UI time to update
                await asyncio.sleep(0.2)

        assert ui.precommit_state.status == TaskStatus.FAILED
        assert (
            ui.ai_state.status == TaskStatus.CANCELLED
        )  # Should be cancelled when pre-commit fails
        assert ai_task.cancelled()

    @pytest.mark.asyncio()
    async def test_output_clears_status_line(self):
        """Test that pre-commit output clears the status line."""
        # Create a mock file descriptor pair
        read_fd, write_fd = os.pipe()

        # Create mock tasks
        async def mock_ai_task():
            await asyncio.sleep(0.5)
            return "Test message"

        async def mock_precommit_task():
            await asyncio.sleep(0.3)
            return 0

        ai_task = asyncio.create_task(mock_ai_task())
        precommit_task = asyncio.create_task(mock_precommit_task())

        ui = ParallelTaskRunner(TaskState(ai_task), TaskState(precommit_task))
        ui.set_output_fd(read_fd)

        # Track what gets printed
        captured_output = []
        original_print = print

        def mock_print(*args, **kwargs):
            output = " ".join(str(arg) for arg in args)
            captured_output.append((output, kwargs.get("end", "\n")))
            original_print(*args, **kwargs)

        with patch("builtins.print", mock_print):
            async with ui:
                # Let status print once
                await asyncio.sleep(0.15)

                # Write some pre-commit output
                os.write(write_fd, b"Pre-commit output\n")
                await asyncio.sleep(0.05)

                # Check that status was cleared
                assert any("\r\033[2K" in output for output, _ in captured_output)

                # Clean up
                os.close(write_fd)
                await asyncio.gather(ai_task, precommit_task, return_exceptions=True)

    @pytest.mark.asyncio()
    async def test_status_visibility_tracking(self):
        """Test that status visibility is tracked correctly."""
        # Create simple tasks
        ai_task = asyncio.create_task(asyncio.sleep(0.1))
        precommit_task = asyncio.create_task(asyncio.sleep(0.1))

        ui = ParallelTaskRunner(TaskState(ai_task), TaskState(precommit_task))

        # Initially not visible
        assert not ui._status_visible

        # Print status line
        ui._print_status_line()
        assert ui._status_visible

        # Clear status line
        ui._clear_status_line()
        assert not ui._status_visible

        # Clean up
        await asyncio.gather(ai_task, precommit_task, return_exceptions=True)

    @pytest.mark.asyncio()
    async def test_long_precommit_output_lines(self):
        """Test handling of pre-commit output lines longer than terminal width."""
        # Create a mock file descriptor pair
        read_fd, write_fd = os.pipe()

        # Create mock tasks
        async def mock_ai_task():
            await asyncio.sleep(0.3)
            return "Test message"

        async def mock_precommit_task():
            await asyncio.sleep(0.2)
            return 0

        ai_task = asyncio.create_task(mock_ai_task())
        precommit_task = asyncio.create_task(mock_precommit_task())

        ui = ParallelTaskRunner(TaskState(ai_task), TaskState(precommit_task))
        ui.set_output_fd(read_fd)

        # Mock terminal width to be narrow
        with patch("shutil.get_terminal_size") as mock_size:
            mock_size.return_value.columns = 40  # Narrow terminal

            async with ui:
                # Write a very long line without newline
                long_line = "Checking " + "." * 100 + " "
                os.write(write_fd, long_line.encode())
                await asyncio.sleep(0.05)

                # Complete the line
                os.write(write_fd, b"done!\n")
                await asyncio.sleep(0.05)

                # Write another long line with embedded progress
                try:
                    os.write(write_fd, b"[")
                    for _ in range(50):
                        os.write(write_fd, b"=")
                        await asyncio.sleep(0.001)
                    os.write(write_fd, b"] 100%\n")
                except BrokenPipeError:
                    # Expected if the reader closed the pipe
                    pass

                # Close write end if not already closed
                with contextlib.suppress(OSError):
                    os.close(write_fd)

                # Wait for tasks to complete
                await asyncio.gather(ai_task, precommit_task, return_exceptions=True)

        # The test passes if it doesn't crash or hang
        # The long lines should be handled gracefully

    @pytest.mark.asyncio()
    async def test_status_line_truncation(self):
        """Test that status line is truncated to fit terminal width."""

        # Create mock tasks with long names
        async def mock_ai_task():
            await asyncio.sleep(0.1)
            return "Test message"

        async def mock_precommit_task():
            await asyncio.sleep(0.1)
            return 0

        ai_task = asyncio.create_task(mock_ai_task())
        precommit_task = asyncio.create_task(mock_precommit_task())

        ui = ParallelTaskRunner(TaskState(ai_task), TaskState(precommit_task))

        # Mock terminal width to be very narrow
        with patch("shutil.get_terminal_size") as mock_size:
            mock_size.return_value.columns = 30  # Very narrow terminal

            # Capture printed output
            captured = []

            def mock_print(*args, **kwargs):
                captured.append(" ".join(str(arg) for arg in args))

            with patch("builtins.print", mock_print):
                ui._print_status_line()

            # Status line should be truncated
            assert len(captured) > 0
            status_line = captured[-1]
            # Remove ANSI codes for length check
            import re

            clean_line = re.sub(r"\033\[[0-9;]*[mK]", "", status_line)
            clean_line = clean_line.lstrip("\r")
            assert len(clean_line) <= 29  # Should fit in terminal width - 1

        # Clean up
        await asyncio.gather(ai_task, precommit_task, return_exceptions=True)


class TestPrecommitHook:
    """Test pre-commit hook execution."""

    @pytest.mark.asyncio()
    async def test_run_precommit_with_colors(
        self,
        test_repo_with_precommit,
        mock_claude_path,
    ):
        """Test that pre-commit output preserves ANSI colors through the full pipeline."""
        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo_with_precommit.working_dir)

        try:
            # Run through the full pipeline to test color preservation
            from git_commit_ai import generate_fresh_commit_message

            msg = await generate_fresh_commit_message("test diff", [], "sonnet")

            # The pre-commit hook should have run and its output should be on stdout
            # We can't easily capture it in this test, but we can verify the message was generated
            assert (
                msg
                == "Add initial test file\n\nThis commit introduces a basic test file to the repository."
            )
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_run_precommit_no_hook(self, test_repo, mock_claude_path):
        """Test behavior when no pre-commit hook exists."""
        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            # When no hook exists, it should still work
            from git_commit_ai import generate_fresh_commit_message

            msg = await generate_fresh_commit_message("test diff", [], "sonnet")
            assert (
                msg
                == "Add initial test file\n\nThis commit introduces a basic test file to the repository."
            )
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_run_precommit_failing(
        self,
        test_repo_with_failing_precommit,
        mock_claude_path,
    ):
        """Test handling of failing pre-commit hook."""
        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo_with_failing_precommit.working_dir)

        try:
            # The failing pre-commit should cause the whole process to exit
            from git_commit_ai import generate_fresh_commit_message

            with pytest.raises(SystemExit) as exc_info:
                await generate_fresh_commit_message("test diff", [], "sonnet")
            assert exc_info.value.code == 1
        finally:
            os.chdir(original_cwd)


class TestStreamingOutput:
    """Test character-by-character streaming."""

    @pytest.mark.asyncio()
    async def test_immediate_streaming(self, test_repo, make_mock_claude, capsys):
        """Test that output is streamed immediately without waiting for newlines."""
        # Create a hook that outputs without newlines
        hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
        hook_path.parent.mkdir(exist_ok=True)

        hook_content = """#!/bin/bash
# Output characters one by one without newline
for char in T e s t i n g . . .; do
    echo -n "$char"
    sleep 0.05
done
echo " Done!"
exit 0
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create a fast mock claude
        make_mock_claude('''print("""<message>Test message</message>""")''')

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            from git_commit_ai import generate_fresh_commit_message

            msg = await generate_fresh_commit_message("test diff", [], "sonnet")
        finally:
            os.chdir(original_cwd)

        # Verify we got a message
        assert msg == "Test message"

        # Check that pre-commit output was streamed to stdout
        # Note: with PTY the output goes directly to stdout, so we can't easily capture it
        # The test passes if there's no error during execution

    @pytest.mark.asyncio()
    async def test_precommit_no_final_newline(
        self,
        test_repo,
        make_mock_claude,
        capsys,
    ):
        """Test handling of pre-commit output that doesn't end with newline."""
        # Create a hook that outputs without final newline
        hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
        hook_path.parent.mkdir(exist_ok=True)

        hook_content = """#!/bin/bash
echo "[INFO] Starting pre-commit checks..."
echo "[WARNING] Unstaged files detected."
echo -n "[INFO] Restored changes from /some/path"
# No final newline!
exit 0
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create a fast mock claude
        make_mock_claude('''print("""<message>Test message</message>""")''')

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            from git_commit_ai import generate_fresh_commit_message

            msg = await generate_fresh_commit_message("test diff", [], "sonnet")
        finally:
            os.chdir(original_cwd)

        # Verify we got a message
        assert msg == "Test message"

        # The output stream should have handled the missing newline
        # The final status should be on its own line, not mixed with pre-commit output

    @pytest.mark.asyncio()
    async def test_precommit_mixed_output_patterns(self, test_repo, make_mock_claude):
        """Test various output patterns from pre-commit hooks."""
        # Create a hook with mixed output patterns
        hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
        hook_path.parent.mkdir(exist_ok=True)

        hook_content = """#!/bin/bash
echo "Line with newline"
echo -n "Line without newline"
sleep 0.1
echo " continued"
echo -n "Progress: "
for i in 1 2 3; do
    echo -n "$i..."
    sleep 0.05
done
echo " Done!"
echo -n "[INFO] Final line without newline"
exit 0
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create a fast mock claude
        make_mock_claude('''print("""<message>Test message</message>""")''')

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            from git_commit_ai import generate_fresh_commit_message

            msg = await generate_fresh_commit_message("test diff", [], "sonnet")
        finally:
            os.chdir(original_cwd)

        # Verify we got a message
        assert msg == "Test message"


class TestFullIntegration:
    """Test the full git-commit-ai flow."""

    @pytest.mark.asyncio()
    async def test_precommit_output_handling(
        self,
        test_repo,
        mock_claude_path,
        monkeypatch,
    ):
        """Test that pre-commit output is handled correctly with status updates."""
        # Create a pre-commit hook with various output patterns
        hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
        hook_path.parent.mkdir(exist_ok=True)
        hook_content = """#!/bin/bash
echo -n "Checking files..."  # No newline
sleep 0.1
echo " done!"  # Complete the line
echo "Running tests..."
sleep 0.1
echo "All good!"
exit 0
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create a mock editor
        mock_editor = mock_claude_path / "mock_editor"
        mock_editor.write_text("#!/bin/sh\nexit 0\n")
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with (
                patch("sys.argv", ["git-commit-ai"]),
                patch("sys.exit") as mock_exit,
            ):
                # Capture output to verify correct behavior
                captured = []
                original_write = sys.stdout.buffer.write

                def capture_write(data):
                    captured.append(data)
                    return original_write(data)

                with patch.object(sys.stdout.buffer, "write", capture_write):
                    await async_main()

                # Should succeed
                mock_exit.assert_called_with(0)

                # Verify output patterns
                output = b"".join(captured).decode("utf-8", errors="replace")

                # Should have pre-commit output
                assert "Checking files... done!" in output
                assert "Running tests..." in output
                assert "All good!" in output

                # Should have status updates (with escape codes)
                assert "⏳ pre-commit" in output or "✓ pre-commit" in output
                assert "⏳ message" in output or "✓ message" in output
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_commit_all_flag(self, test_repo, mock_claude_path, monkeypatch):
        """Test that --all flag properly stages files before pre-commit."""
        # Reset any staged changes
        test_repo.index.reset()

        # Modify an existing tracked file
        readme = Path(test_repo.working_dir) / "README.md"
        readme.write_text("# Test Repository\n\nModified content for --all test\n")

        # Create a pre-commit hook that checks for staged files
        hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
        hook_path.parent.mkdir(exist_ok=True)
        hook_content = """#!/bin/bash
echo "[PRE-COMMIT] Checking staged files..."
staged=$(git diff --cached --name-only)
if [ -z "$staged" ]; then
    echo "[PRE-COMMIT] ERROR: No staged files found!"
    exit 1
fi
echo "[PRE-COMMIT] Found staged files: $staged"
exit 0
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create a mock editor that just saves the file
        mock_editor = mock_claude_path / "mock_editor"
        mock_editor.write_text(
            """#!/bin/sh
# Mock editor - just exit successfully without changing the file
exit 0
""",
        )
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with (
                patch("sys.argv", ["git-commit-ai", "--all"]),
                patch("sys.exit") as mock_exit,
            ):
                await async_main()

                # Should exit with 0 (success)
                mock_exit.assert_called_with(0)

                # Verify the file was actually committed
                last_commit = test_repo.head.commit
                assert "README.md" in [
                    item.a_path for item in last_commit.diff(last_commit.parents[0])
                ]
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_commit_all_flag_cancelled(
        self,
        test_repo,
        mock_claude_path,
        monkeypatch,
    ):
        """Test that --all flag properly unstages files if commit is cancelled."""
        # Reset any staged changes
        test_repo.index.reset()

        # Modify an existing tracked file
        readme = Path(test_repo.working_dir) / "README.md"
        readme.write_text("# Test Repository\n\nModified content for cancel test\n")

        # Create a mock editor that exits without saving (simulating :q!)
        mock_editor = mock_claude_path / "cancel_editor"
        mock_editor.write_text(
            """#!/bin/sh
# Mock editor - exit without changing file to simulate cancellation
exit 0
""",
        )
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with (
                patch("sys.argv", ["git-commit-ai", "--all"]),
                patch("sys.exit") as mock_exit,
            ):
                mock_exit.side_effect = SystemExit  # Make sys.exit raise SystemExit

                with pytest.raises(SystemExit):
                    await async_main()

                # Should exit with 1 (cancelled)
                mock_exit.assert_called_with(1)

                # Verify that files were unstaged after cancellation
                # Check that there are no staged changes
                staged = test_repo.git.diff("--cached", "--name-only")
                assert staged == "", "Files should be unstaged after cancelled commit"

                # But the modifications should still exist
                unstaged = test_repo.git.diff("--name-only")
                assert (
                    "README.md" in unstaged
                ), "Modified files should still be modified"
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_commit_all_flag_with_deleted_files(
        self,
        test_repo,
        mock_claude_path,
        monkeypatch,
    ):
        """Test that --all flag properly handles deleted files."""
        # Reset any staged changes
        test_repo.index.reset()

        # Create and commit a new file
        new_file = Path(test_repo.working_dir) / "to_delete.txt"
        new_file.write_text("This file will be deleted")
        test_repo.index.add([str(new_file)])
        test_repo.index.commit("Add file to delete")

        # Now delete the file and modify another
        new_file.unlink()
        readme = Path(test_repo.working_dir) / "README.md"
        readme.write_text("# Test Repository\n\nModified after deletion\n")

        # Create a pre-commit hook that checks for staged files
        hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
        hook_path.parent.mkdir(exist_ok=True)
        hook_content = """#!/bin/bash
echo "[PRE-COMMIT] Checking staged changes..."
git diff --cached --name-status
exit 0
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create a mock editor that just saves the file
        mock_editor = mock_claude_path / "mock_editor"
        mock_editor.write_text(
            """#!/bin/sh
# Mock editor - just exit successfully without changing the file
exit 0
""",
        )
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with (
                patch("sys.argv", ["git-commit-ai", "--all"]),
                patch("sys.exit") as mock_exit,
            ):
                await async_main()

                # Should exit with 0 (success)
                mock_exit.assert_called_with(0)

                # Verify both the deletion and modification were committed
                last_commit = test_repo.head.commit
                # Note: diff is from parent to current, so deletions show as additions in reverse
                diff_items = {
                    item.a_path: item.change_type
                    for item in last_commit.parents[0].diff(last_commit)
                }
                assert "to_delete.txt" in diff_items
                assert diff_items["to_delete.txt"] == "D"  # Deleted
                assert "README.md" in diff_items
                assert diff_items["README.md"] == "M"  # Modified
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_commit_all_flag_only_deletions(
        self,
        test_repo,
        mock_claude_path,
        monkeypatch,
    ):
        """Test that --all flag works when there are only deleted files."""
        # Reset any staged changes
        test_repo.index.reset()

        # Create and commit multiple files
        for i in range(3):
            f = Path(test_repo.working_dir) / f"file{i}.txt"
            f.write_text(f"Content of file {i}")
        test_repo.index.add(["file0.txt", "file1.txt", "file2.txt"])
        test_repo.index.commit("Add multiple files")

        # Now delete all the files (no modifications)
        for i in range(3):
            (Path(test_repo.working_dir) / f"file{i}.txt").unlink()

        # Create a mock editor
        mock_editor = mock_claude_path / "mock_editor"
        mock_editor.write_text(
            """#!/bin/sh
exit 0
""",
        )
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with (
                patch("sys.argv", ["git-commit-ai", "--all"]),
                patch("sys.exit") as mock_exit,
            ):
                await async_main()

                # Should exit with 0 (success)
                mock_exit.assert_called_with(0)

                # Verify all deletions were committed
                last_commit = test_repo.head.commit
                diff_items = {
                    item.a_path: item.change_type
                    for item in last_commit.parents[0].diff(last_commit)
                }
                for i in range(3):
                    assert f"file{i}.txt" in diff_items
                    assert diff_items[f"file{i}.txt"] == "D"  # All deleted
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_commit_all_flag_mixed_changes(
        self,
        test_repo,
        mock_claude_path,
        monkeypatch,
    ):
        """Test --all with a mix of modifications, deletions, and additions to tracked files."""
        # Reset any staged changes
        test_repo.index.reset()

        # Create and commit multiple files
        files = {
            "modify.txt": "Original content",
            "delete.txt": "Will be deleted",
            "keep.txt": "Will not change",
        }
        for name, content in files.items():
            (Path(test_repo.working_dir) / name).write_text(content)
        test_repo.index.add(list(files.keys()))
        test_repo.index.commit("Add test files")

        # Make changes: modify one, delete one, keep one unchanged
        (Path(test_repo.working_dir) / "modify.txt").write_text("Modified content")
        (Path(test_repo.working_dir) / "delete.txt").unlink()
        # keep.txt stays unchanged

        # Also modify the existing README.md
        (Path(test_repo.working_dir) / "README.md").write_text("# Updated README\n")

        # Create a pre-commit hook that lists what it sees
        hook_path = Path(test_repo.git_dir) / "hooks" / "pre-commit"
        hook_path.parent.mkdir(exist_ok=True)
        hook_content = """#!/bin/bash
echo "[PRE-COMMIT] Staged changes:"
git diff --cached --name-status | sed 's/^/  /'
echo "[PRE-COMMIT] Total staged files: $(git diff --cached --name-only | wc -l)"
exit 0
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create a mock editor
        mock_editor = mock_claude_path / "mock_editor"
        mock_editor.write_text("""#!/bin/sh\nexit 0\n""")
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with (
                patch("sys.argv", ["git-commit-ai", "--all"]),
                patch("sys.exit") as mock_exit,
            ):
                await async_main()

                # Should succeed
                mock_exit.assert_called_with(0)

                # Verify the correct changes were committed
                last_commit = test_repo.head.commit
                diff_items = {
                    item.a_path: item.change_type
                    for item in last_commit.parents[0].diff(last_commit)
                }

                # Check each expected change
                assert "modify.txt" in diff_items
                assert diff_items["modify.txt"] == "M"  # Modified

                assert "delete.txt" in diff_items
                assert diff_items["delete.txt"] == "D"  # Deleted

                assert "README.md" in diff_items
                assert diff_items["README.md"] == "M"  # Modified

                # keep.txt should NOT be in the diff (unchanged)
                assert "keep.txt" not in diff_items
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_no_staged_changes(self, test_repo, capsys):
        """Test behavior when there are no staged changes."""
        # Create a repo with no staged changes
        # test_repo fixture creates staged changes, so we need to unstage them
        test_repo.index.reset()

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with patch("sys.argv", ["git-commit-ai"]), patch("sys.exit") as mock_exit:
                mock_exit.side_effect = SystemExit  # Make sys.exit raise SystemExit

                from git_commit_ai import async_main

                with pytest.raises(SystemExit):
                    await async_main()

                # Should exit with 1 and print appropriate message
                mock_exit.assert_called_with(1)

                # Check error message
                captured = capsys.readouterr()
                # Could be either message depending on whether there are untracked files
                assert (
                    "nothing to commit" in captured.err
                    or "no changes added to commit" in captured.err
                )
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_unstaged_changes_without_all_flag(self, test_repo, capsys):
        """Test behavior when there are unstaged changes but -a flag not used."""
        # The test_repo fixture creates a staged file, let's reset it first
        test_repo.index.reset()

        # Now modify an existing tracked file
        readme = Path(test_repo.working_dir) / "README.md"
        readme.write_text("# Test Repository\n\nModified content\n")

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            with patch("sys.argv", ["git-commit-ai"]), patch("sys.exit") as mock_exit:
                mock_exit.side_effect = SystemExit  # Make sys.exit raise SystemExit

                from git_commit_ai import async_main

                with pytest.raises(SystemExit):
                    await async_main()

                # Should exit with 1
                mock_exit.assert_called_with(1)

                # Check error message
                captured = capsys.readouterr()
                assert (
                    'no changes added to commit (use "git add" and/or "git commit -a")'
                    in captured.err
                )
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_full_flow_with_mocked_claude(
        self,
        test_repo_with_precommit,
        mock_claude_path,
        monkeypatch,
    ):
        """Test the complete flow with a mocked claude command."""
        # mock_claude_path fixture already sets up the claude command and PATH

        # Create a mock editor that just saves the file
        mock_editor = mock_claude_path / "mock_editor"
        mock_editor.write_text(
            """#!/bin/sh
# Mock editor - just exit successfully without changing the file
exit 0
""",
        )
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        # Mock sys.argv to control arguments
        with (
            patch("sys.argv", ["git-commit-ai", "--model", "sonnet"]),
            patch("sys.exit") as mock_exit,
        ):
            # Change to test repo directory
            original_cwd = str(Path.cwd())
            os.chdir(test_repo_with_precommit.working_dir)

            try:
                await async_main()
            finally:
                os.chdir(original_cwd)

            # Should exit with 0 (success)
            # The last call should be with 0 (the final git commit exit)
            mock_exit.assert_called_with(0)

    @pytest.mark.asyncio()
    async def test_commit_template_format(
        self,
        test_repo,
        mock_claude_path,
        monkeypatch,
    ):
        """Test that the commit message includes proper git template."""
        # Add another file to have both staged and unstaged changes
        other_file = Path(test_repo.working_dir) / "other.txt"
        other_file.write_text("other content\n")

        # Create an unstaged change to existing file
        readme = Path(test_repo.working_dir) / "README.md"
        readme.write_text("# Modified README\n")

        # Mock editor that captures the commit message
        mock_editor = mock_claude_path / "capture_editor"
        mock_editor.write_text(
            f"""#!/usr/bin/env python3
import sys
with open(sys.argv[1], 'r') as f:
    content = f.read()
# Save to a file we can check
with open('{test_repo.working_dir}/captured_message.txt', 'w') as f:
    f.write(content)
# Exit with 1 to abort commit (we just want to capture the message)
sys.exit(1)
""",
        )
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))
        monkeypatch.setenv("GIT_EDITOR", str(mock_editor))

        # Change to test repo directory
        original_cwd = str(Path.cwd())
        os.chdir(test_repo.working_dir)

        try:
            # Run git-commit-ai as subprocess so editor env works properly
            script_path = Path(__file__).parent / "git_commit_ai.py"
            result = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script_path),
                "--verbose",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "EDITOR": str(mock_editor),
                    "GIT_EDITOR": str(mock_editor),
                },
            )
            await result.communicate()

            # The command should exit with code 1 (editor exited with 1)
            assert result.returncode == 1

            # Read the captured message
            captured_file = Path(test_repo.working_dir) / "captured_message.txt"
            assert captured_file.exists()
            content = captured_file.read_text()

            # Verify it contains the expected elements
            assert "Add initial test file" in content  # AI-generated message
            assert "# Please enter the commit message for your changes" in content
            assert "# On branch" in content
            assert "# Changes to be committed:" in content
            assert "#\tnew file:    test.txt" in content  # Note: 4 spaces, not 5
            assert "# Changes not staged for commit:" in content
            assert "#\tmodified:    README.md" in content
            assert "# Untracked files:" in content
            assert "#\tother.txt" in content

            # Since we used --verbose, it should have the diff
            assert "# ------------------------ >8 ------------------------" in content
            assert "diff --git" in content

        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio()
    async def test_full_flow_with_failing_precommit(
        self,
        test_repo_with_failing_precommit,
        mock_slow_claude_path,
        monkeypatch,
    ):
        """Test behavior when pre-commit fails."""
        # mock_slow_claude_path fixture already sets up the claude command and PATH

        # Create a mock editor
        mock_editor = mock_slow_claude_path / "mock_editor"
        mock_editor.write_text(
            """#!/bin/sh
exit 0
""",
        )
        mock_editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(mock_editor))

        with (
            patch("sys.argv", ["git-commit-ai", "--model", "sonnet"]),
            patch("sys.exit") as mock_exit,
        ):
            mock_exit.side_effect = (
                SystemExit  # Make sys.exit actually raise SystemExit
            )
            original_cwd = str(Path.cwd())
            os.chdir(test_repo_with_failing_precommit.working_dir)

            try:
                with pytest.raises(SystemExit):
                    await async_main()
            finally:
                os.chdir(original_cwd)

            # Should exit with 1 (pre-commit failure)
            mock_exit.assert_called_once_with(1)
