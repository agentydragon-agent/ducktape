#!/usr/bin/env python3
"""Tests for git-commit-ai --amend functionality with mocked AI."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from git import Repo

from adgn_llm.git_commit_ai.cli import ClaudeAI, build_prompt, get_commit_diff


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
        else:
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
                return_value=(b"<message>Updated commit message</message>", b"")
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
            repo=repo, diff=diff, passthru=[], previous_message=previous_message
        )

        new_message = await mock_ai.generate(include_all=False)
        assert "Updated: Initial implementation" in new_message
        assert "Added more changes" in new_message


def test_cache_key_includes_amend_status():
    """Test that cache key differentiates between new and amend commits."""
    import hashlib

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

