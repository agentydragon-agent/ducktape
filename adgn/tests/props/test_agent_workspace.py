"""Tests for agent_workspace module."""

import os
from pathlib import Path
from uuid import UUID

import pytest

from adgn.props.agent_workspace import (
    DEFAULT_WORKSPACES_BASE,
    get_workspace_path,
    get_workspaces_base,
)


class TestGetWorkspacesBase:
    """Tests for get_workspaces_base()."""

    def test_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without env var, returns default path."""
        monkeypatch.delenv("ADGN_WORKSPACES_DIR", raising=False)
        result = get_workspaces_base()
        assert result == DEFAULT_WORKSPACES_BASE
        assert result == Path.home() / ".local" / "share" / "adgn" / "workspaces"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ADGN_WORKSPACES_DIR env var overrides default."""
        custom_path = "/tmp/custom/workspaces"
        monkeypatch.setenv("ADGN_WORKSPACES_DIR", custom_path)
        result = get_workspaces_base()
        assert result == Path(custom_path)

    def test_env_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty env var is treated as not set (uses default)."""
        monkeypatch.setenv("ADGN_WORKSPACES_DIR", "")
        result = get_workspaces_base()
        # Empty string is falsy, so falls back to default
        assert result == DEFAULT_WORKSPACES_BASE


class TestGetWorkspacePath:
    """Tests for get_workspace_path()."""

    def test_path_includes_run_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Workspace path includes agent_run_id."""
        monkeypatch.delenv("ADGN_WORKSPACES_DIR", raising=False)
        run_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = get_workspace_path(run_id)
        assert result.name == "550e8400-e29b-41d4-a716-446655440000"
        assert result.parent == DEFAULT_WORKSPACES_BASE

    def test_path_is_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same run_id always produces same path."""
        monkeypatch.delenv("ADGN_WORKSPACES_DIR", raising=False)
        run_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        result1 = get_workspace_path(run_id)
        result2 = get_workspace_path(run_id)
        assert result1 == result2

    def test_different_run_ids_produce_different_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different run_ids produce different paths."""
        monkeypatch.delenv("ADGN_WORKSPACES_DIR", raising=False)
        run_id1 = UUID("550e8400-e29b-41d4-a716-446655440000")
        run_id2 = UUID("660e8400-e29b-41d4-a716-446655440001")
        result1 = get_workspace_path(run_id1)
        result2 = get_workspace_path(run_id2)
        assert result1 != result2

    def test_respects_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Workspace path uses custom base from env var."""
        custom_path = "/tmp/test/workspaces"
        monkeypatch.setenv("ADGN_WORKSPACES_DIR", custom_path)
        run_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = get_workspace_path(run_id)
        assert result == Path(custom_path) / "550e8400-e29b-41d4-a716-446655440000"

    def test_path_is_absolute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Workspace path is absolute when using default."""
        monkeypatch.delenv("ADGN_WORKSPACES_DIR", raising=False)
        run_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = get_workspace_path(run_id)
        assert result.is_absolute()

    def test_does_not_create_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """get_workspace_path does not create the directory (pure path helper)."""
        monkeypatch.setenv("ADGN_WORKSPACES_DIR", str(tmp_path))
        run_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = get_workspace_path(run_id)
        # Path is returned but directory is not created
        assert not result.exists()
