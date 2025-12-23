"""Tests for agent-definition CLI commands."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tarfile

import pytest
from typer.testing import CliRunner

from adgn.props.cli.cmd_agent_definition import app
from adgn.props.definition_utils import pack_definition, validate_definition


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
    """Tests for validate_definition function."""

    def test_valid_definition_returns_empty(self, valid_definition: Path) -> None:
        """Valid definition returns no errors."""
        errors = validate_definition(valid_definition)
        assert errors == []

    def test_missing_agent_md(self, definition_missing_agent_md: Path) -> None:
        """Missing AGENT.md returns error."""
        errors = validate_definition(definition_missing_agent_md)
        assert len(errors) == 1
        assert "AGENT.md" in errors[0]

    def test_missing_init(self, definition_missing_init: Path) -> None:
        """Missing init script returns error."""
        errors = validate_definition(definition_missing_init)
        assert len(errors) == 1
        assert "init" in errors[0]

    def test_non_executable_init(self, definition_non_executable_init: Path) -> None:
        """Non-executable init script returns error."""
        errors = validate_definition(definition_non_executable_init)
        assert len(errors) == 1
        assert "executable" in errors[0]

    def test_multiple_errors(self, tmp_path: Path) -> None:
        """Multiple missing files return multiple errors."""
        # Empty directory
        errors = validate_definition(tmp_path)
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
        assert "Not a directory" in result.output

    def test_nonexistent_path_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        """Non-existent path fails."""
        result = runner.invoke(app, ["validate", str(tmp_path / "does_not_exist")])
        assert result.exit_code == 1


class TestPackDefinition:
    """Tests for pack_definition function."""

    def test_external_symlink_resolved(self, tmp_path: Path) -> None:
        """Symlinks pointing outside definition dir are resolved to content."""
        # Create external file
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "shared.md"
        external_file.write_text("# Shared Content\n\nThis is shared documentation.")

        # Create definition directory with symlink to external file
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()

        agent_md = definition_dir / "AGENT.md"
        agent_md.write_text("# Test Agent\n")

        init_script = definition_dir / "init"
        init_script.write_text("#!/bin/bash\necho 'hi'\n")
        init_script.chmod(0o755)

        docs_dir = definition_dir / "docs"
        docs_dir.mkdir()

        # Create symlink to external file
        symlink = docs_dir / "shared.md"
        symlink.symlink_to(external_file)

        # Pack the definition
        archive = pack_definition(definition_dir)

        # Extract and verify content was included (not a symlink)
        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "docs/shared.md" in names

            # Read the content - should be the resolved content, not a symlink
            member = tar.getmember("docs/shared.md")
            assert member.isfile()  # Not a symlink
            assert not member.issym()

            # Extract and verify content matches
            content = tar.extractfile(member)
            assert content is not None
            text = content.read().decode("utf-8")
            assert "Shared Content" in text

    def test_internal_symlink_preserved(self, tmp_path: Path) -> None:
        """Symlinks pointing inside definition dir work correctly."""
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()

        agent_md = definition_dir / "AGENT.md"
        agent_md.write_text("# Test Agent\n")

        init_script = definition_dir / "init"
        init_script.write_text("#!/bin/bash\necho 'hi'\n")
        init_script.chmod(0o755)

        # Create internal file and symlink to it
        original = definition_dir / "original.md"
        original.write_text("# Original\n")

        link = definition_dir / "link.md"
        link.symlink_to(original)

        # Pack the definition
        archive = pack_definition(definition_dir)

        # Extract and verify both files exist
        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "original.md" in names
            assert "link.md" in names

    def test_regular_files_included(self, tmp_path: Path) -> None:
        """Regular files are included in archive."""
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()

        agent_md = definition_dir / "AGENT.md"
        agent_md.write_text("# Test Agent\n")

        init_script = definition_dir / "init"
        init_script.write_text("#!/bin/bash\necho 'hi'\n")
        init_script.chmod(0o755)

        # Pack and verify
        archive = pack_definition(definition_dir)
        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "AGENT.md" in names
            assert "init" in names

    def test_external_directory_symlink_resolved_recursively(self, tmp_path: Path) -> None:
        """Directory symlinks pointing outside definition dir are resolved to content."""
        # Create external directory with nested files
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_docs = external_dir / "docs"
        external_docs.mkdir()
        (external_docs / "shared_a.md").write_text("# Shared A\n")
        (external_docs / "shared_b.md").write_text("# Shared B\n")
        # Nested subdirectory
        external_subdir = external_docs / "sub"
        external_subdir.mkdir()
        (external_subdir / "nested.md").write_text("# Nested\n")

        # Create definition directory with symlink to external directory
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()

        agent_md = definition_dir / "AGENT.md"
        agent_md.write_text("# Test Agent\n")

        init_script = definition_dir / "init"
        init_script.write_text("#!/bin/bash\necho 'hi'\n")
        init_script.chmod(0o755)

        # Create directory symlink to external docs
        docs_link = definition_dir / "docs"
        docs_link.symlink_to(external_docs)

        # Pack the definition
        archive = pack_definition(definition_dir)

        # Extract and verify all content was included
        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "docs/shared_a.md" in names
            assert "docs/shared_b.md" in names
            assert "docs/sub/nested.md" in names

            # Verify they're files, not symlinks
            for name in ["docs/shared_a.md", "docs/shared_b.md", "docs/sub/nested.md"]:
                member = tar.getmember(name)
                assert member.isfile()
                assert not member.issym()

    def test_external_symlink_rejected_when_resolve_disabled(self, tmp_path: Path) -> None:
        """External symlinks raise ValueError when resolve_symlinks=False."""
        # Create external file
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "secret.txt"
        external_file.write_text("sensitive data")

        # Create definition directory with symlink to external file
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()

        agent_md = definition_dir / "AGENT.md"
        agent_md.write_text("# Test Agent\n")

        init_script = definition_dir / "init"
        init_script.write_text("#!/bin/bash\necho 'hi'\n")
        init_script.chmod(0o755)

        # Create symlink to external file (simulating directory escape attempt)
        symlink = definition_dir / "escape.txt"
        symlink.symlink_to(external_file)

        # With resolve_symlinks=False, should raise ValueError
        with pytest.raises(ValueError, match="External symlink not allowed"):
            pack_definition(definition_dir, resolve_symlinks=False)

    def test_external_directory_symlink_rejected_when_resolve_disabled(self, tmp_path: Path) -> None:
        """External directory symlinks raise ValueError when resolve_symlinks=False."""
        # Create external directory
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        (external_dir / "file.txt").write_text("external content")

        # Create definition directory with symlink to external directory
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()

        agent_md = definition_dir / "AGENT.md"
        agent_md.write_text("# Test Agent\n")

        init_script = definition_dir / "init"
        init_script.write_text("#!/bin/bash\necho 'hi'\n")
        init_script.chmod(0o755)

        # Create directory symlink to external directory
        symlink = definition_dir / "external_docs"
        symlink.symlink_to(external_dir)

        # With resolve_symlinks=False, should raise ValueError
        with pytest.raises(ValueError, match="External symlink not allowed"):
            pack_definition(definition_dir, resolve_symlinks=False)

    def test_internal_symlink_allowed_when_resolve_disabled(self, tmp_path: Path) -> None:
        """Internal symlinks are allowed even when resolve_symlinks=False."""
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()

        agent_md = definition_dir / "AGENT.md"
        agent_md.write_text("# Test Agent\n")

        init_script = definition_dir / "init"
        init_script.write_text("#!/bin/bash\necho 'hi'\n")
        init_script.chmod(0o755)

        # Create internal file and symlink to it
        original = definition_dir / "original.md"
        original.write_text("# Original\n")

        link = definition_dir / "link.md"
        link.symlink_to(original)

        # With resolve_symlinks=False, internal symlinks should still work
        archive = pack_definition(definition_dir, resolve_symlinks=False)

        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "original.md" in names
            assert "link.md" in names
