"""Tests for agent_handle module."""

import io
from pathlib import Path
import tarfile

import pytest

from adgn.props.agent_handle import _load_definition_archive, _unpack_definition


class TestUnpackDefinition:
    """Tests for _unpack_definition helper."""

    def test_creates_target_dir(self, tmp_path: Path) -> None:
        """Creates target directory if it doesn't exist."""
        # Create a simple tar archive
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            data = b"test content"
            info = tarfile.TarInfo(name="test.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        archive = buffer.getvalue()

        # Unpack to non-existent directory
        target = tmp_path / "subdir" / "nested"
        assert not target.exists()
        _unpack_definition(archive, target)

        assert target.exists()
        assert (target / "test.txt").read_text() == "test content"

    def test_extracts_nested_structure(self, tmp_path: Path) -> None:
        """Preserves directory structure in archive."""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            # Add a nested file
            data = b"nested content"
            info = tarfile.TarInfo(name="subdir/file.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        archive = buffer.getvalue()

        _unpack_definition(archive, tmp_path)
        assert (tmp_path / "subdir" / "file.txt").read_text() == "nested content"


class TestLoadDefinitionArchive:
    """Tests for _load_definition_archive helper.

    Note: These tests require database with agent_definitions table.
    They verify that the function correctly raises ValueError for missing definitions.
    """

    def test_raises_for_missing_definition(self, synced_test_db) -> None:
        """Raises ValueError for non-existent definition ID."""
        with pytest.raises(ValueError, match="Agent definition not found"):
            _load_definition_archive("nonexistent-definition-id")


# Integration tests for AgentHandle.create() would require:
# - A populated agent_definitions table with a test definition
# - Mock MCP client and compositor
# - Docker environment for init script execution
#
# These are deferred to e2e/integration tests since they require
# significant infrastructure setup beyond the scope of unit tests.
