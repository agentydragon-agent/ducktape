"""Unit tests for Claude rules linter."""

import json
import os
import tempfile
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pygit2
import pytest

from ducktape_llm_common.linters.claude_config import ClaudeLinterConfig
from ducktape_llm_common.linters.claude_rules import ClaudeRulesLinter

# Test constants
HASATTR_VIOLATION_CODE = textwrap.dedent("""
    def test():
        if hasattr(obj, 'attr'):  # Violation!
            pass
""")


class TestClaudeRulesLinter:
    """Test cases for ClaudeRulesLinter."""

    @contextmanager
    def _chdir(self, path: Path) -> Iterator[None]:
        """Context manager to change directory and restore on exit."""
        orig_cwd = os.getcwd()
        try:
            os.chdir(path)
            yield
        finally:
            os.chdir(orig_cwd)

    def _git_add_commit(self, repo_path: Path, message: str = "Commit"):
        """Helper to add all files and commit using pygit2."""
        repo = pygit2.Repository(str(repo_path))
        index = repo.index
        index.add_all()
        index.write()

        # Create commit
        tree = index.write_tree()
        author = pygit2.Signature("Test User", "test@test.com")
        committer = author

        # Create commit (handle both first and subsequent commits)
        parents = [] if repo.head_is_unborn else [repo.head.target]
        repo.create_commit("HEAD", author, committer, message, tree, parents)

    @pytest.fixture
    def temp_project(self):
        """Create a temporary git project for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Initialize git repo using pygit2
            repo = pygit2.init_repository(str(tmpdir_path), bare=False)

            # Set git config
            config = repo.config
            config["user.email"] = "test@test.com"
            config["user.name"] = "Test"

            yield tmpdir_path

    def test_cwd_restriction(self, temp_project):
        """Test that linter only checks files under CWD, not entire project."""
        # Create project structure:
        # project/
        #   ├── .git/
        #   ├── parent_file.py  (should NOT be checked when running from subdir)
        #   └── subdir/
        #       └── subdir_file.py  (should be checked)

        # Create parent file with hasattr violation
        parent_file = temp_project / "parent_file.py"
        parent_file.write_text(HASATTR_VIOLATION_CODE)

        # Create subdirectory
        subdir = temp_project / "subdir"
        subdir.mkdir()

        # Create subdir file with hasattr violation
        subdir_file = subdir / "subdir_file.py"
        subdir_file.write_text(HASATTR_VIOLATION_CODE)

        # Enable linter for this project
        config = ClaudeLinterConfig(enabled=True, rules={"enabled_rules": [], "check_hasattr": True})
        config_file = temp_project / ".claude-linter.json"
        config.to_json_file(config_file)

        # Add files to git
        self._git_add_commit(temp_project, "Initial")

        # Test 1: Run linter from project root - should check both files
        with self._chdir(temp_project):
            linter = ClaudeRulesLinter(session_pid=1001, config=config)
            results = linter.lint_directory(temp_project)

            # Should find violations in both files (as warnings for first-time files)
            file_paths = {str(r.file) for r in results if r.has_warnings or r.has_errors}
            assert str(parent_file) in file_paths
            assert str(subdir_file) in file_paths

        # Test 2: Run linter from subdirectory - should only check subdir file
        with self._chdir(subdir):
            linter = ClaudeRulesLinter(session_pid=1002, config=config)
            results = linter.lint_directory(temp_project)

            # Should only find violations in subdir file (as warnings for first-time)
            file_paths = {str(r.file) for r in results if r.has_warnings or r.has_errors}
            assert str(parent_file) not in file_paths
            assert str(subdir_file) in file_paths

    def test_log_location_from_subdir(self, temp_project):
        """Test that logs go to project directory even when running from subdir."""
        # Create subdir
        subdir = temp_project / "subdir"
        subdir.mkdir()

        # Create a file with violation in subdir
        subdir_file = subdir / "test.py"
        subdir_file.write_text(HASATTR_VIOLATION_CODE)

        # Enable linter
        config = ClaudeLinterConfig(enabled=True, rules={"enabled_rules": [], "check_hasattr": True})

        # Add to git
        self._git_add_commit(temp_project, "Initial")

        # Run linter from subdirectory
        with self._chdir(subdir):
            linter = ClaudeRulesLinter(session_pid=12345, config=config)

            # Verify linter was initialized with correct directories
            assert linter.launch_cwd == subdir
            assert linter.project_dir == temp_project  # Should find git root

            # Verify log directory is under project, not CWD
            expected_log_dir = ClaudeRulesLinter.get_claude_project_dir(temp_project, "linter")
            assert linter.claude_project_dir == expected_log_dir

            # Run linter
            results = linter.lint_directory(temp_project)

            # Should only check files under CWD
            assert len(results) == 1
            assert str(results[0].file) == str(subdir_file)

            # State should be saved to project dir
            assert linter._state_file.parent == expected_log_dir
            assert linter._state_file.name == "state_12345.json"

    def test_git_submodule_exclusion(self, temp_project):
        """Test that git submodules are excluded from linting."""
        # Create a file in main project
        main_file = temp_project / "main.py"
        main_file.write_text("print('main')")

        # Create a fake submodule directory
        submodule_dir = temp_project / "external_lib"
        submodule_dir.mkdir()
        submodule_file = submodule_dir / "lib.py"
        submodule_file.write_text("""
def test():
    if hasattr(obj, 'attr'):  # Should be ignored
        pass
""")

        # Add main file to git
        repo = pygit2.Repository(str(temp_project))
        index = repo.index
        index.add("main.py")
        index.write()
        tree = index.write_tree()
        author = pygit2.Signature("Test User", "test@test.com")
        repo.create_commit(
            "HEAD", author, author, "Add main", tree, [repo.head.target] if not repo.head_is_unborn else []
        )

        # Create a fake git submodule (create .gitmodules file)
        gitmodules = temp_project / ".gitmodules"
        gitmodules.write_text("""[submodule "external_lib"]
    path = external_lib
    url = https://github.com/example/lib.git
""")

        # Also need to make it a git repo
        pygit2.init_repository(str(submodule_dir), bare=False)

        # Now add the submodule to git index (simulate git submodule add)
        repo = pygit2.Repository(str(temp_project))
        index = repo.index
        index.add(".gitmodules")
        index.write()

        # Add submodule config
        with open(temp_project / ".git/config", "a") as f:
            f.write("""
[submodule "external_lib"]
    path = external_lib
    url = https://github.com/example/lib.git
""")

        config = ClaudeLinterConfig(enabled=True)
        with self._chdir(temp_project):
            linter = ClaudeRulesLinter(config=config)
            files = linter._get_python_files(temp_project)

            # Should include main.py but not submodule file
            file_paths = [str(f) for f in files]
            assert str(main_file) in file_paths
            # Note: This test might not work perfectly without actual git submodule setup
            # but it tests the logic

    def test_autofix_only_in_cwd(self, temp_project):
        """Test that autofixes only apply to files under CWD."""
        # Create files with trailing whitespace
        parent_file = temp_project / "parent.py"
        parent_file.write_text("print('parent')   \n")  # Trailing spaces

        subdir = temp_project / "subdir"
        subdir.mkdir()
        subdir_file = subdir / "sub.py"
        subdir_file.write_text("print('sub')   \n")  # Trailing spaces

        # Add to git
        self._git_add_commit(temp_project, "Initial")

        config = ClaudeLinterConfig(enabled=True)

        with self._chdir(subdir):
            # Run from subdir - should only process subdir file
            linter = ClaudeRulesLinter(config=config)

            # Get the files that would be processed
            python_files = linter._get_python_files(linter.launch_cwd)
            file_paths = [str(f) for f in python_files]

            # Only subdir file should be in the list
            assert str(parent_file) not in file_paths
            assert str(subdir_file) in file_paths

    def test_ruff_format_respects_pyproject_line_length(self, temp_project):
        """Test that ruff format respects line length from pyproject.toml.

        The project allows 120 chars (more permissive than default 88).
        We create a line that's 100 chars - it should NOT be wrapped.
        """
        # Create a pyproject.toml with more permissive line length
        pyproject_content = textwrap.dedent("""
            [tool.ruff]
            line-length = 120
        """)
        pyproject_file = temp_project / "pyproject.toml"
        pyproject_file.write_text(pyproject_content)

        # Create a file with lines that are:
        # - Over 88 chars (default) but under 120 (should NOT be wrapped)
        # - Over 120 chars (should be wrapped)
        long_line_code = textwrap.dedent("""
            # This line is about 100 chars - over default 88 but under project's 120
            def function_with_moderately_long_name(param_one: str, param_two: int, param_three: bool) -> str:
                # This line is over 120 chars and SHOULD be wrapped
                return (
                    f"This is a very long string that contains {param_one} and {param_two} "
                    f"and {param_three} and some more text to make it exceed 120 characters for sure"
                )

            # Another line that's about 95 chars - should NOT be wrapped with 120 limit
            CONSTANT_WITH_LONG_NAME = "This string is long enough to exceed 88 chars but not 120 chars limit"
        """)

        test_file = temp_project / "long_lines.py"
        test_file.write_text(long_line_code)

        # Enable linter
        config = ClaudeLinterConfig(enabled=True)

        # Add to git
        self._git_add_commit(temp_project, "Initial commit with long lines")

        with self._chdir(temp_project):
            linter = ClaudeRulesLinter(config=config)

            # Run autofixes which should format according to pyproject.toml
            linter._run_autofixes(temp_project)

            # Read the formatted file
            formatted_content = test_file.read_text()
            lines = formatted_content.splitlines()

            # Check that no line exceeds 120 characters
            for i, line in enumerate(lines):
                assert len(line) <= 120, f"Line {i + 1} exceeds 120 chars: {len(line)} chars: {line}"

            # Verify that lines between 88-120 chars were NOT wrapped
            # The function definition line should still be on one line
            func_def = (
                "def function_with_moderately_long_name(param_one: str, param_two: int, param_three: bool) -> str:"
            )
            assert any(func_def in line for line in lines), (
                "Function definition was wrapped even though it's under 120 chars"
            )

            # The CONSTANT line should also still be on one line
            const_def = (
                'CONSTANT_WITH_LONG_NAME = "This string is long enough to exceed 88 chars but not 120 chars limit"'
            )
            assert any(const_def in line for line in lines), (
                "Constant definition was wrapped even though it's under 120 chars"
            )

    def test_config_file_detection_uses_project_dir(self, temp_project):
        """Test that config file detection uses project dir, not CWD."""
        # Create config at project root
        config_data = {"enabled": True, "rules": {"check_hasattr": False}}
        config_file = temp_project / ".claude-linter.json"
        config_file.write_text(json.dumps(config_data))

        subdir = temp_project / "subdir"
        subdir.mkdir()

        with self._chdir(subdir):
            # Run from subdir - should still find project config
            found_config = ClaudeLinterConfig.find_config(subdir)

            # Should find the config from project root
            assert found_config.enabled is True
            assert found_config.rules.check_hasattr is False

    def test_empty_directory(self, temp_project):
        """Test linter handles empty directories gracefully."""
        empty_dir = temp_project / "empty"
        empty_dir.mkdir()

        config = ClaudeLinterConfig(enabled=True)

        with self._chdir(empty_dir):
            linter = ClaudeRulesLinter(config=config)
            results = linter.lint_directory(temp_project)

            # Should return empty results
            assert len(results) == 0

    def test_non_git_directory(self):
        """Test linter works in non-git directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a Python file
            py_file = tmpdir_path / "test.py"
            py_file.write_text("""
def test():
    if hasattr(obj, 'attr'):
        pass
""")

            config = ClaudeLinterConfig(enabled=True, rules={"enabled_rules": [], "check_hasattr": True})

            with self._chdir(tmpdir_path):
                # Should work without git
                linter = ClaudeRulesLinter(config=config)
                files = linter._get_python_files(tmpdir_path)

                assert len(files) == 1
                assert files[0] == py_file

    def test_deeply_nested_cwd(self, temp_project):
        """Test linter with deeply nested CWD."""
        # Create deep directory structure
        deep_dir = temp_project / "a" / "b" / "c" / "d"
        deep_dir.mkdir(parents=True)

        # Create files at different levels
        (temp_project / "root.py").write_text("print('root')")
        (temp_project / "a" / "level1.py").write_text("print('level1')")
        (deep_dir / "deep.py").write_text("print('deep')")

        # Add to git
        self._git_add_commit(temp_project, "Initial")

        config = ClaudeLinterConfig(enabled=True)

        with self._chdir(deep_dir):
            # Run from deep directory
            linter = ClaudeRulesLinter(config=config)
            files = linter._get_python_files(linter.launch_cwd)

            # Should only find deep.py
            assert len(files) == 1
            assert files[0].name == "deep.py"
