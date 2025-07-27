"""Integration tests for WorktreeService with real git repositories."""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from wt.server.worktree_service import WorktreeService
from wt.shared.configuration import Configuration
from wt.shared.git_interface import GitInterface
from wt.server.github_client import GitHubInterface


class TestWorktreeService:
    """Test the WorktreeService with real git repositories."""

    @pytest.fixture(scope="function")
    def service(self, real_temp_repo, real_env):
        """Create WorktreeService with real dependencies and real git repo."""
        from tests.conftest import build_test_configuration
        
        # Use centralized helper to create configuration
        config = build_test_configuration(
            real_temp_repo,
            branch_prefix="test/",
            default_worktree_base_branch="main",
            github_repo="test-user/test-repo",
            github_enabled=False,
            log_operations=True
        )
        
        # Create real GitInterface with proper initialization
        git = GitInterface(config=config)
        github = Mock()  # Keep GitHub mocked for now
        
        return WorktreeService(git, github), config

    def test_list_worktrees_empty_repo(self, service):
        """Test listing worktrees in empty repository."""
        worktree_service, config = service
        
        # Fresh repo has no worktrees except main
        result = worktree_service.list_worktrees(config)
        
        # Should be empty since we filter out the main repo
        assert len(result) == 0

    def test_create_and_list_worktree(self, service):
        """Test creating a worktree and listing it."""
        worktree_service, config = service
        
        # Create a real worktree
        worktree_path = worktree_service.create_worktree(config, "test-branch")
        
        # Verify it was created
        assert worktree_path.exists()
        assert worktree_path.name == "test-branch"
        
        # List worktrees and verify it appears
        result = worktree_service.list_worktrees(config)
        assert len(result) == 1
        
        name, path, exists = result[0]
        assert name == "test-branch"
        assert path == worktree_path
        assert exists is True

    def test_worktree_removal(self, service):
        """Test removing a worktree."""
        worktree_service, config = service
        
        # Create a worktree first
        worktree_path = worktree_service.create_worktree(config, "to-remove")
        assert worktree_path.exists()
        
        # Remove it (using async method)
        import asyncio
        asyncio.run(worktree_service.remove_worktree(config, "to-remove", force=True))
        
        # Verify it's gone
        assert not worktree_path.exists()
        
        # List should be empty again
        result = worktree_service.list_worktrees(config)
        assert len(result) == 0

    def test_worktree_path_resolution(self, service):
        """Test worktree path methods."""
        worktree_service, config = service
        
        # Test path calculation
        expected_path = config.worktrees_dir / "test-name"
        actual_path = worktree_service.get_worktree_path(config, "test-name")
        assert actual_path == expected_path

    def test_is_managed_worktree_filtering(self, service):
        """Test worktree filtering logic with real paths."""
        worktree_service, config = service
        
        # Main repo should not be managed
        main_repo_path = config.main_repo
        assert not worktree_service._is_managed_worktree(main_repo_path, config)
        
        # Path outside worktrees dir should not be managed
        outside_path = Path("/tmp/outside-worktree")
        assert not worktree_service._is_managed_worktree(outside_path, config)
        
        # Path inside worktrees dir should be managed
        inside_path = config.worktrees_dir / "valid-worktree"
        assert worktree_service._is_managed_worktree(inside_path, config)

    def test_post_creation_script_execution(self, real_temp_repo, real_env):
        """Test that post-creation script is executed when configured."""
        # Create a simple test script
        script_path = real_temp_repo / "test_script.sh"
        script_path.write_text("""#!/bin/bash
echo "Script executed with arg: $1" > "$1/script_output.txt"
""")
        script_path.chmod(0o755)
        
        # Use centralized helper to create configuration with script
        from tests.conftest import build_test_configuration
        
        config = build_test_configuration(
            real_temp_repo,
            branch_prefix="test/",
            default_worktree_base_branch="main",
            github_repo="test-user/test-repo",
            github_enabled=False,
            log_operations=True,
            post_creation_script=str(script_path)
        )
        
        # Create WorktreeService with the script-enabled config
        git = GitInterface(config=config)
        github = Mock()
        worktree_service = WorktreeService(git, github)
        
        # Create worktree - script should execute
        worktree_path = worktree_service.create_worktree(config, "script-test")
        
        # Verify script was executed
        output_file = worktree_path / "script_output.txt"
        assert output_file.exists()
        content = output_file.read_text()
        assert str(worktree_path) in content
        assert "Script executed with arg:" in content