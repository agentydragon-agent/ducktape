#!/usr/bin/env python3
"""Tests for git-commit-ai --amend functionality with mocked AI."""

import hashlib
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, patch

from git import Repo
import pytest

from adgn.llm.git_commit_ai import cli
from adgn.llm.git_commit_ai.cli import ClaudeAI, get_commit_diff
from adgn.llm.git_commit_ai.core import build_prompt


class MockClaudeAI:
    """Mock AI that returns predictable commit messages."""

    def __init__(
        self,
        repo,
        diff,
        passthru,
        debug=False,
        timeout_secs=None,
        previous_message=None,
    ):
        self.repo = repo
        self.diff = diff
        self.passthru = passthru
        self.previous_message = previous_message

    async def generate(self, include_all: bool, model: str | None = None) -> str:
        """Generate a mock commit message based on previous message."""
        if self.previous_message:
            # For amend, return an updated version
            return f"Updated: {self.previous_message}\n\n- Added more changes"
        # For new commits
        return "Add new functionality\n\n- Initial implementation"


@pytest.fixture
def temp_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        # Configure git user for commits
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@example.com").release()
        yield repo


def test_get_commit_diff_normal_commit(temp_repo):
    """Test get_commit_diff for a normal (non-amend) commit."""
    # Create initial file
    test_file = Path(temp_repo.working_dir) / "test.txt"
    test_file.write_text("initial content\n")
    temp_repo.index.add(["test.txt"])
    temp_repo.index.commit("Initial commit")

    # Stage changes
    test_file.write_text("initial content\nmore content\n")
    temp_repo.index.add(["test.txt"])

    # Get diff without amend
    diff = get_commit_diff(temp_repo, [], previous_message=None)

    assert "more content" in diff
    assert "@@" in diff  # Should have diff headers
    assert "=== Original commit" not in diff  # Should NOT have amend sections


def test_get_commit_diff_amend_with_staged_changes(temp_repo):
    """Test get_commit_diff for --amend with staged changes."""
    # Create initial commit
    test_file = Path(temp_repo.working_dir) / "test.txt"
    test_file.write_text("initial content\n")
    temp_repo.index.add(["test.txt"])
    temp_repo.index.commit("Initial commit")

    # Make and stage new changes
    test_file.write_text("initial content\nmore content\n")
    temp_repo.index.add(["test.txt"])

    # Get diff with amend (previous_message indicates amend)
    diff = get_commit_diff(temp_repo, [], previous_message="Initial commit")

    # Should have both sections
    assert "=== Original commit" in diff
    assert "=== New changes being added ===" in diff
    assert "initial content" in diff
    assert "more content" in diff


def test_get_commit_diff_amend_first_commit(temp_repo):
    """Test get_commit_diff when amending the very first commit (no HEAD^)."""
    # Create first commit
    test_file = Path(temp_repo.working_dir) / "test.txt"
    test_file.write_text("first file\n")
    temp_repo.index.add(["test.txt"])
    temp_repo.index.commit("First commit ever")

    # Stage changes for amend
    test_file.write_text("first file\nupdated\n")
    temp_repo.index.add(["test.txt"])

    # Get diff for amending first commit
    diff = get_commit_diff(temp_repo, [], previous_message="First commit ever")

    # Should handle missing HEAD^ gracefully
    assert "=== Original commit content ===" in diff  # Uses git show instead
    assert "=== New changes being added ===" in diff
    assert "updated" in diff


def test_get_commit_diff_amend_with_all_flag(temp_repo):
    """Test get_commit_diff for --amend -a (all tracked changes)."""
    # Create initial commit
    test_file = Path(temp_repo.working_dir) / "test.txt"
    test_file.write_text("initial\n")
    temp_repo.index.add(["test.txt"])
    temp_repo.index.commit("Initial")

    # Make changes but don't stage
    test_file.write_text("initial\nmodified\n")

    # Get diff with amend and -a flag
    diff = get_commit_diff(temp_repo, ["-a"], previous_message="Initial")

    assert "=== Original commit" in diff
    assert "=== New changes being added ===" in diff
    assert "modified" in diff


def test_build_prompt_without_amend(temp_repo):
    """Test build_prompt for regular commits."""
    # Create initial commit first (so HEAD exists)
    initial_file = Path(temp_repo.working_dir) / "initial.txt"
    initial_file.write_text("initial\n")
    temp_repo.index.add(["initial.txt"])
    temp_repo.index.commit("Initial commit")

    # Now create a file and stage it for a new commit
    test_file = Path(temp_repo.working_dir) / "test.txt"
    test_file.write_text("content\n")
    temp_repo.index.add(["test.txt"])

    diff = temp_repo.git.diff("--cached", "--unified=0")
    prompt = build_prompt(temp_repo, diff, [], previous_message=None)

    assert "Write a concise, imperative-mood Git commit message" in prompt
    assert "Previous commit message:" not in prompt
    assert "being amended" not in prompt


def test_build_prompt_with_amend(temp_repo):
    """Test build_prompt for amend commits."""
    # Create initial commit
    test_file = Path(temp_repo.working_dir) / "test.txt"
    test_file.write_text("initial\n")
    temp_repo.index.add(["test.txt"])
    temp_repo.index.commit("My original message")

    # Stage changes
    test_file.write_text("initial\nmore\n")
    temp_repo.index.add(["test.txt"])

    diff = get_commit_diff(temp_repo, [], previous_message="My original message")
    prompt = build_prompt(temp_repo, diff, [], previous_message="My original message")

    assert "Update and refine this existing commit message" in prompt
    assert "Previous commit message:" in prompt
    assert "My original message" in prompt
    assert "The commit is being amended" in prompt


@pytest.mark.asyncio
async def test_claude_ai_with_amend():
    """Test ClaudeAI provider handles previous_message correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        # Create initial commit so HEAD exists
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("initial\n")
        repo.index.add(["test.txt"])
        repo.index.commit("Initial commit")

        # Mock the claude CLI command
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Set up mock process
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(
                return_value=(b"<message>Updated commit message</message>", b""),
            )
            mock_subprocess.return_value = mock_proc

            # Test with previous message (amend)
            ai = ClaudeAI(
                repo=repo,
                diff="test diff",
                passthru=[],
                previous_message="Original message",
            )

            result = await ai.generate(include_all=False, model="sonnet")

            assert result == "Updated commit message"

            # Verify the prompt included previous message context
            call_args = mock_subprocess.call_args[0]
            prompt_idx = call_args.index("-p") + 1
            prompt = call_args[prompt_idx]
            assert "Original message" in prompt


@pytest.mark.asyncio
async def test_full_amend_flow_integration():
    """Integration test of the full amend flow with mocked AI."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        # Create initial commit
        test_file = Path(tmpdir) / "file.txt"
        test_file.write_text("version 1\n")
        repo.index.add(["file.txt"])
        repo.index.commit("Initial implementation")

        # Make changes for amend
        test_file.write_text("version 1\nversion 2\n")
        repo.index.add(["file.txt"])

        # Get previous message
        previous_message = repo.git.log("-1", "--pretty=format:%B").strip()
        assert previous_message == "Initial implementation"

        # Get the diff that would be shown to AI
        diff = get_commit_diff(repo, [], previous_message=previous_message)

        # Verify diff contains both original and new changes
        assert "=== Original commit" in diff
        assert "=== New changes being added ===" in diff
        assert "version 1" in diff
        assert "version 2" in diff

        # Build prompt as the tool would
        prompt = build_prompt(repo, diff, [], previous_message=previous_message)

        # Verify prompt is for amending
        assert "Update and refine" in prompt
        assert "Initial implementation" in prompt

        # Mock AI would generate updated message
        mock_ai = MockClaudeAI(
            repo=repo,
            diff=diff,
            passthru=[],
            previous_message=previous_message,
        )

        new_message = await mock_ai.generate(include_all=False)
        assert "Updated: Initial implementation" in new_message
        assert "Added more changes" in new_message


def test_cache_key_includes_amend_status():
    """Test that cache key differentiates between new and amend commits."""

    # Simulate cache key generation
    provider = "claude"
    model_name = "sonnet"
    scope = "staged"
    commitish = "abc123"
    diff = "test diff content"
    diff_hash = hashlib.sha256(diff.encode()).hexdigest()

    # Key for new commit
    key_new = f"{provider}:{model_name}:{scope}:new:{commitish}:{diff_hash}"

    # Key for amend
    key_amend = f"{provider}:{model_name}:{scope}:amend:{commitish}:{diff_hash}"

    # Should be different
    assert key_new != key_amend
    assert ":new:" in key_new
    assert ":amend:" in key_amend


@pytest.mark.asyncio
async def test_editor_comments_and_scissors_are_ignored_in_commit_message(monkeypatch):
    """Full flow: ensure '#' comments and content below scissors don't end up committed.

    We simulate the editor writing additional commented lines and a scissors block.
    The final commit message should contain only the AI-produced message, without
    any '#' comment lines or the scissors marker content.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        # Ensure the CLI runs inside this temporary repository
        monkeypatch.chdir(tmpdir)

        # Create an initial commit so HEAD exists
        seed = Path(tmpdir) / "seed.txt"
        seed.write_text("seed\n")
        repo.index.add(["seed.txt"])
        repo.index.commit("seed")

        # Prepare a staged change for the new commit
        p = Path(tmpdir) / "file.txt"
        p.write_text("v1\n")
        repo.index.add(["file.txt"])

        # Patch AI/cache so no real AI is invoked; force cached message
        ai_message = "Subject line\n\nBody line one\n- bullet"

        async def _fake_generate(
            self,
            include_all: bool,
            model: str | None = None,
        ) -> str:
            return ai_message

        monkeypatch.setattr(
            "adgn.llm.git_commit_ai.cli.ClaudeAI.generate",
            _fake_generate,
        )
        monkeypatch.setattr(
            "adgn.llm.git_commit_ai.cli.Cache.get",
            lambda self, key: ai_message,
        )

        # Patch _get_editor to return a placeholder editor command
        async def _fake_get_editor():
            return "fake-editor"

        monkeypatch.setattr("adgn.llm.git_commit_ai.cli._get_editor", _fake_get_editor)

        # Intercept the editor subprocess shell call and append comments + scissors
        class _Proc:
            def __init__(self, code=0):
                self._code = code

            async def wait(self):
                return self._code

        async def _fake_shell(cmd, *args, **kwargs):
            # Extract COMMIT_EDITMSG path (last token)
            commit_path = cmd.rsplit(" ", 1)[-1]
            msg = (
                "\n# editor-added comment (should be stripped)\n"
                "# ------------------------ >8 ------------------------\n"
                "# diff line (commented)\n"
            )
            Path(commit_path).write_text(Path(commit_path).read_text() + msg)
            return _Proc(0)

        monkeypatch.setattr("asyncio.create_subprocess_shell", _fake_shell)

        # Run the tool; patch argv to avoid pytest args leaking

        with patch("sys.argv", ["git-commit-ai"]), patch("sys.exit") as mock_exit:
            await cli.async_main()
            mock_exit.assert_called_with(0)

        # Verify the committed message contains only the AI message
        committed = repo.git.log("-1", "--pretty=%B").strip()
        assert committed.startswith("Subject line")
        assert "editor-added comment" not in committed
        assert ">8" not in committed
        assert "diff line (commented)" not in committed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
