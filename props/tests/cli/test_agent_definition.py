"""Tests for agent-definition CLI commands.

Note: pack_definition now only validates Dockerfile presence in tar.
AGENT.md and init are validated in the built Docker image via definition_builder.validate_image().
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tarfile

import pytest
from typer.testing import CliRunner

from props.cli.cmd_agent_definition import app
from props.definition_utils import (
    DOCKERFILE_FILE,
    DefinitionValidationError,
    pack_definition,
    validate_packed_definition,
)


@pytest.fixture
def runner() -> CliRunner:
    """CLI test runner."""
    return CliRunner()


def _create_minimal_dockerfile(path: Path) -> None:
    """Create a minimal Dockerfile that copies AGENT.md and init."""
    (path / DOCKERFILE_FILE).write_text(
        "FROM python:3.12-slim\nCOPY AGENT.md /AGENT.md\nCOPY init /init\nRUN chmod +x /init\n"
    )


@pytest.fixture
def valid_definition(tmp_path: Path) -> Path:
    """Create a valid agent definition directory with Dockerfile."""
    _create_minimal_dockerfile(tmp_path)

    (tmp_path / "AGENT.md").write_text("# Test Agent\n\nA test agent definition.")

    init_script = tmp_path / "init"
    init_script.write_text("#!/bin/bash\necho 'initialized'\n")
    init_script.chmod(0o755)

    return tmp_path


@pytest.fixture
def definition_missing_dockerfile(tmp_path: Path) -> Path:
    """Create definition with missing Dockerfile."""
    (tmp_path / "AGENT.md").write_text("# Test Agent\n")

    init_script = tmp_path / "init"
    init_script.write_text("#!/bin/bash\necho 'initialized'\n")
    init_script.chmod(0o755)
    return tmp_path


class TestPackAndValidate:
    """Tests for pack_definition with validation.

    Note: pack_definition only validates Dockerfile presence.
    AGENT.md and init are validated in the built image.
    """

    def test_valid_definition_no_error(self, valid_definition: Path) -> None:
        """Valid definition (with Dockerfile) packs without error."""
        archive = pack_definition(valid_definition)
        assert len(archive) > 0

    def test_missing_dockerfile(self, definition_missing_dockerfile: Path) -> None:
        """Missing Dockerfile raises DefinitionValidationError."""
        with pytest.raises(DefinitionValidationError) as exc_info:
            pack_definition(definition_missing_dockerfile)
        assert len(exc_info.value.errors) == 1
        assert DOCKERFILE_FILE in exc_info.value.errors[0]

    def test_empty_directory_fails(self, tmp_path: Path) -> None:
        """Empty directory fails with Dockerfile missing error."""
        with pytest.raises(DefinitionValidationError) as exc_info:
            pack_definition(tmp_path)
        errors = exc_info.value.errors
        assert len(errors) == 1
        assert DOCKERFILE_FILE in errors[0]


class TestValidatePackedDefinition:
    """Tests for validate_packed_definition function."""

    def test_valid_archive(self, valid_definition: Path) -> None:
        """Valid archive passes validation."""
        archive = pack_definition(valid_definition)
        # Already validated by pack_definition, but validate_packed_definition should also pass
        validate_packed_definition(archive)

    def test_missing_dockerfile_in_archive(self) -> None:
        """Archive missing Dockerfile raises DefinitionValidationError."""
        # Create archive directly without Dockerfile
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            # Add AGENT.md and init, but no Dockerfile
            agent_md = b"# Test Agent\n"
            info = tarfile.TarInfo(name="AGENT.md")
            info.size = len(agent_md)
            tar.addfile(info, BytesIO(agent_md))

            init_content = b"#!/bin/bash\necho test"
            info = tarfile.TarInfo(name="init")
            info.size = len(init_content)
            info.mode = 0o755
            tar.addfile(info, BytesIO(init_content))
        archive = buffer.getvalue()

        with pytest.raises(DefinitionValidationError) as exc_info:
            validate_packed_definition(archive)
        assert DOCKERFILE_FILE in exc_info.value.errors[0]


class TestCmdValidate:
    """Tests for validate CLI command."""

    def test_valid_definition_success(self, runner: CliRunner, valid_definition: Path) -> None:
        """Valid definition exits with code 0."""
        result = runner.invoke(app, ["validate", str(valid_definition)])
        assert result.exit_code == 0
        assert "Valid agent definition" in result.output

    def test_invalid_definition_fails(self, runner: CliRunner, definition_missing_dockerfile: Path) -> None:
        """Invalid definition exits with non-zero code (exception propagates)."""
        result = runner.invoke(app, ["validate", str(definition_missing_dockerfile)])
        assert result.exit_code != 0


def _setup_definition_base(definition_dir: Path) -> None:
    """Set up minimal Dockerfile, AGENT.md, and init for a definition directory."""
    _create_minimal_dockerfile(definition_dir)
    (definition_dir / "AGENT.md").write_text("# Test Agent\n")
    init_script = definition_dir / "init"
    init_script.write_text("#!/bin/bash\necho 'hi'\n")
    init_script.chmod(0o755)


class TestPackDefinition:
    """Tests for pack_definition function."""

    def test_internal_symlink_preserved(self, tmp_path: Path) -> None:
        """Symlinks pointing inside definition dir work correctly."""
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()
        _setup_definition_base(definition_dir)

        original = definition_dir / "original.md"
        original.write_text("# Original\n")

        link = definition_dir / "link.md"
        link.symlink_to(original)

        archive = pack_definition(definition_dir)

        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "original.md" in names
            assert "link.md" in names

    def test_regular_files_included(self, tmp_path: Path) -> None:
        """Regular files are included in archive."""
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()
        _setup_definition_base(definition_dir)

        archive = pack_definition(definition_dir)
        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert DOCKERFILE_FILE in names
            assert "AGENT.md" in names
            assert "init" in names

    def test_external_symlink_rejected(self, tmp_path: Path) -> None:
        """External symlinks raise ValueError."""
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "secret.txt"
        external_file.write_text("sensitive data")

        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()
        _setup_definition_base(definition_dir)

        symlink = definition_dir / "escape.txt"
        symlink.symlink_to(external_file)

        with pytest.raises(ValueError, match="External symlink not allowed"):
            pack_definition(definition_dir)

    def test_external_directory_symlink_rejected(self, tmp_path: Path) -> None:
        """External directory symlinks raise ValueError."""
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        (external_dir / "file.txt").write_text("external content")

        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()
        _setup_definition_base(definition_dir)

        symlink = definition_dir / "external_docs"
        symlink.symlink_to(external_dir)

        with pytest.raises(ValueError, match="External symlink not allowed"):
            pack_definition(definition_dir)

    def test_internal_symlink_allowed(self, tmp_path: Path) -> None:
        """Internal symlinks are allowed."""
        definition_dir = tmp_path / "definition"
        definition_dir.mkdir()
        _setup_definition_base(definition_dir)

        original = definition_dir / "original.md"
        original.write_text("# Original\n")

        link = definition_dir / "link.md"
        link.symlink_to(original)

        archive = pack_definition(definition_dir)

        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "original.md" in names
            assert "link.md" in names
