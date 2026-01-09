"""Tests for agent-pkg CLI commands.

Note: pack_agent_pkg only validates Dockerfile presence in tar.
The /init script is validated in the built Docker image via agent_pkg.builder.validate_image().
"""

from __future__ import annotations

import tarfile
from io import BytesIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from props.core.agent_pkg_utils import (
    DOCKERFILE_FILE,
    AgentPkgValidationError,
    pack_agent_pkg,
    validate_packed_agent_pkg,
)
from props.core.cli.cmd_agent_pkg import app


@pytest.fixture
def runner() -> CliRunner:
    """CLI test runner."""
    return CliRunner()


def _create_minimal_dockerfile(path: Path) -> None:
    """Create a minimal Dockerfile that copies init."""
    (path / DOCKERFILE_FILE).write_text("FROM python:3.12-slim\nCOPY init /init\nRUN chmod +x /init\n")


@pytest.fixture
def valid_pkg(tmp_path: Path) -> Path:
    """Create a valid agent package directory with Dockerfile and init."""
    _create_minimal_dockerfile(tmp_path)

    init_script = tmp_path / "init"
    init_script.write_text("#!/bin/bash\necho 'initialized'\n")
    init_script.chmod(0o755)

    return tmp_path


@pytest.fixture
def pkg_missing_dockerfile(tmp_path: Path) -> Path:
    """Create package with missing Dockerfile."""
    init_script = tmp_path / "init"
    init_script.write_text("#!/bin/bash\necho 'initialized'\n")
    init_script.chmod(0o755)
    return tmp_path


class TestPackAndValidate:
    """Tests for pack_agent_pkg with validation.

    Note: pack_agent_pkg only validates Dockerfile presence.
    /init is validated in the built image.
    """

    def test_valid_pkg_no_error(self, valid_pkg: Path) -> None:
        """Valid package (with Dockerfile) packs without error."""
        archive = pack_agent_pkg(valid_pkg)
        assert len(archive) > 0

    def test_missing_dockerfile(self, pkg_missing_dockerfile: Path) -> None:
        """Missing Dockerfile raises AgentPkgValidationError."""
        with pytest.raises(AgentPkgValidationError) as exc_info:
            pack_agent_pkg(pkg_missing_dockerfile)
        assert len(exc_info.value.errors) == 1
        assert DOCKERFILE_FILE in exc_info.value.errors[0]

    def test_empty_directory_fails(self, tmp_path: Path) -> None:
        """Empty directory fails with Dockerfile missing error."""
        with pytest.raises(AgentPkgValidationError) as exc_info:
            pack_agent_pkg(tmp_path)
        errors = exc_info.value.errors
        assert len(errors) == 1
        assert DOCKERFILE_FILE in errors[0]


class TestValidatePackedAgentPkg:
    """Tests for validate_packed_agent_pkg function."""

    def test_valid_archive(self, valid_pkg: Path) -> None:
        """Valid archive passes validation."""
        archive = pack_agent_pkg(valid_pkg)
        # Already validated by pack_agent_pkg, but validate_packed_agent_pkg should also pass
        validate_packed_agent_pkg(archive)

    def test_missing_dockerfile_in_archive(self) -> None:
        """Archive missing Dockerfile raises AgentPkgValidationError."""
        # Create archive directly without Dockerfile
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            # Add init, but no Dockerfile
            init_content = b"#!/bin/bash\necho test"
            info = tarfile.TarInfo(name="init")
            info.size = len(init_content)
            info.mode = 0o755
            tar.addfile(info, BytesIO(init_content))
        archive = buffer.getvalue()

        with pytest.raises(AgentPkgValidationError) as exc_info:
            validate_packed_agent_pkg(archive)
        assert DOCKERFILE_FILE in exc_info.value.errors[0]


class TestCmdValidate:
    """Tests for validate CLI command."""

    def test_valid_pkg_success(self, runner: CliRunner, valid_pkg: Path) -> None:
        """Valid package exits with code 0."""
        result = runner.invoke(app, ["validate", str(valid_pkg)])
        assert result.exit_code == 0
        assert "Valid agent package" in result.output

    def test_invalid_pkg_fails(self, runner: CliRunner, pkg_missing_dockerfile: Path) -> None:
        """Invalid package exits with non-zero code (exception propagates)."""
        result = runner.invoke(app, ["validate", str(pkg_missing_dockerfile)])
        assert result.exit_code != 0


def _setup_pkg_base(pkg_dir: Path) -> None:
    """Set up minimal Dockerfile and init for a package directory."""
    _create_minimal_dockerfile(pkg_dir)
    init_script = pkg_dir / "init"
    init_script.write_text("#!/bin/bash\necho 'hi'\n")
    init_script.chmod(0o755)


class TestPackAgentPkg:
    """Tests for pack_agent_pkg function."""

    def test_internal_symlink_preserved(self, tmp_path: Path) -> None:
        """Symlinks pointing inside package dir work correctly."""
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        _setup_pkg_base(pkg_dir)

        original = pkg_dir / "original.md"
        original.write_text("# Original\n")

        link = pkg_dir / "link.md"
        link.symlink_to(original)

        archive = pack_agent_pkg(pkg_dir)

        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "original.md" in names
            assert "link.md" in names

    def test_regular_files_included(self, tmp_path: Path) -> None:
        """Regular files are included in archive."""
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        _setup_pkg_base(pkg_dir)

        archive = pack_agent_pkg(pkg_dir)
        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert DOCKERFILE_FILE in names
            assert "init" in names

    def test_external_symlink_rejected(self, tmp_path: Path) -> None:
        """External symlinks raise ValueError."""
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "secret.txt"
        external_file.write_text("sensitive data")

        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        _setup_pkg_base(pkg_dir)

        symlink = pkg_dir / "escape.txt"
        symlink.symlink_to(external_file)

        with pytest.raises(ValueError, match="External symlink not allowed"):
            pack_agent_pkg(pkg_dir)

    def test_external_directory_symlink_rejected(self, tmp_path: Path) -> None:
        """External directory symlinks raise ValueError."""
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        (external_dir / "file.txt").write_text("external content")

        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        _setup_pkg_base(pkg_dir)

        symlink = pkg_dir / "external_docs"
        symlink.symlink_to(external_dir)

        with pytest.raises(ValueError, match="External symlink not allowed"):
            pack_agent_pkg(pkg_dir)

    def test_internal_symlink_allowed(self, tmp_path: Path) -> None:
        """Internal symlinks are allowed."""
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        _setup_pkg_base(pkg_dir)

        original = pkg_dir / "original.md"
        original.write_text("# Original\n")

        link = pkg_dir / "link.md"
        link.symlink_to(original)

        archive = pack_agent_pkg(pkg_dir)

        with tarfile.open(fileobj=BytesIO(archive), mode="r") as tar:
            names = tar.getnames()
            assert "original.md" in names
            assert "link.md" in names
