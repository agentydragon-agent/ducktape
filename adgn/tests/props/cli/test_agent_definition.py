"""Tests for agent-definition CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from adgn.props.cli.cmd_agent_definition import _validate_definition, app


@pytest.fixture
def runner() -> CliRunner:
    """CLI test runner."""
    return CliRunner()


@pytest.fixture
def valid_definition(tmp_path: Path) -> Path:
    """Create a valid agent definition directory."""
    # Create AGENT.md
    agent_md = tmp_path / "AGENT.md"
    agent_md.write_text("# Test Agent\n\nA test agent definition.")

    # Create executable init script
    init_script = tmp_path / "init"
    init_script.write_text("#!/bin/bash\necho 'initialized'\n")
    init_script.chmod(0o755)

    return tmp_path


@pytest.fixture
def definition_missing_agent_md(tmp_path: Path) -> Path:
    """Create definition with missing AGENT.md."""
    init_script = tmp_path / "init"
    init_script.write_text("#!/bin/bash\necho 'initialized'\n")
    init_script.chmod(0o755)
    return tmp_path


@pytest.fixture
def definition_missing_init(tmp_path: Path) -> Path:
    """Create definition with missing init script."""
    agent_md = tmp_path / "AGENT.md"
    agent_md.write_text("# Test Agent\n")
    return tmp_path


@pytest.fixture
def definition_non_executable_init(tmp_path: Path) -> Path:
    """Create definition with non-executable init script."""
    agent_md = tmp_path / "AGENT.md"
    agent_md.write_text("# Test Agent\n")
    init_script = tmp_path / "init"
    init_script.write_text("#!/bin/bash\necho 'initialized'\n")
    # Don't make executable
    return tmp_path


class TestValidateDefinition:
    """Tests for _validate_definition function."""

    def test_valid_definition_returns_empty(self, valid_definition: Path) -> None:
        """Valid definition returns no errors."""
        errors = _validate_definition(valid_definition)
        assert errors == []

    def test_missing_agent_md(self, definition_missing_agent_md: Path) -> None:
        """Missing AGENT.md returns error."""
        errors = _validate_definition(definition_missing_agent_md)
        assert len(errors) == 1
        assert "AGENT.md" in errors[0]

    def test_missing_init(self, definition_missing_init: Path) -> None:
        """Missing init script returns error."""
        errors = _validate_definition(definition_missing_init)
        assert len(errors) == 1
        assert "init" in errors[0]

    def test_non_executable_init(self, definition_non_executable_init: Path) -> None:
        """Non-executable init script returns error."""
        errors = _validate_definition(definition_non_executable_init)
        assert len(errors) == 1
        assert "executable" in errors[0]

    def test_multiple_errors(self, tmp_path: Path) -> None:
        """Multiple missing files return multiple errors."""
        # Empty directory
        errors = _validate_definition(tmp_path)
        assert len(errors) == 2
        assert any("AGENT.md" in e for e in errors)
        assert any("init" in e for e in errors)


class TestCmdValidate:
    """Tests for validate CLI command."""

    def test_valid_definition_success(self, runner: CliRunner, valid_definition: Path) -> None:
        """Valid definition exits with code 0."""
        result = runner.invoke(app, ["validate", str(valid_definition)])
        assert result.exit_code == 0
        assert "Valid agent definition" in result.output

    def test_invalid_definition_fails(self, runner: CliRunner, definition_missing_agent_md: Path) -> None:
        """Invalid definition exits with code 1."""
        result = runner.invoke(app, ["validate", str(definition_missing_agent_md)])
        assert result.exit_code == 1
        assert "Validation failed" in result.output

    def test_non_directory_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        """Non-directory path fails."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        result = runner.invoke(app, ["validate", str(file_path)])
        assert result.exit_code == 1
        assert "not a directory" in result.output

    def test_nonexistent_path_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        """Non-existent path fails."""
        result = runner.invoke(app, ["validate", str(tmp_path / "does_not_exist")])
        assert result.exit_code == 1
