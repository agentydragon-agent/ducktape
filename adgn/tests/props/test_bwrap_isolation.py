#!/usr/bin/env python3
"""Tests for bubblewrap-based isolation."""

import sys
from pathlib import Path
import tempfile
import pytest

from props_core.bwrap_isolation import BwrapIsolation, run_with_bwrap, is_bwrap_available

# Skip all tests if bwrap not available
pytestmark = pytest.mark.skipif(not is_bwrap_available(), reason="bubblewrap not installed")


def test_bwrap_available():
    """Test that bwrap is detected as available."""
    assert is_bwrap_available()


def test_basic_execution():
    """Test basic command execution in bwrap."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "test.txt").write_text("Hello bwrap!")

        result = run_with_bwrap(
            ["cat", "/workspace/test.txt"],
            workspace_root=workspace,
        )

        assert result.returncode == 0
        assert "Hello bwrap!" in result.stdout


def test_python_execution():
    """Test Python code execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        script = workspace / "test.py"
        script.write_text("print('Isolated Python!')")

        result = run_with_bwrap(
            ["python3", "test.py"],
            workspace_root=workspace,
        )

        assert result.returncode == 0
        assert "Isolated Python!" in result.stdout


def test_readonly_workspace():
    """Test that readonly workspace prevents writes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "original.txt").write_text("Original")

        # Try to write to readonly workspace
        result = run_with_bwrap(
            ["sh", "-c", "echo 'evil' > /workspace/evil.txt"],
            workspace_root=workspace,
            readonly=True,
        )

        # Should fail
        assert result.returncode != 0
        # File should not exist on host
        assert not (workspace / "evil.txt").exists()


def test_filesystem_isolation():
    """Test that sandbox cannot access parent filesystem."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Try to list root directory
        result = run_with_bwrap(
            ["ls", "/"],
            workspace_root=workspace,
        )

        assert result.returncode == 0
        # Should see workspace but not full host filesystem
        assert "workspace" in result.stdout
        # Should not see typical host directories like home
        assert "home" not in result.stdout or "usr" in result.stdout  # usr is mounted


def test_file_creation():
    """Test that agent can create files in writable workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        result = run_with_bwrap(
            ["sh", "-c", "echo 'created' > /workspace/new.txt"],
            workspace_root=workspace,
            readonly=False,
        )

        assert result.returncode == 0
        assert (workspace / "new.txt").exists()
        assert (workspace / "new.txt").read_text().strip() == "created"


def test_python_agent_simulation():
    """Test running a realistic Python agent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Create task files
        (workspace / "input.txt").write_text("Process this")

        agent_code = """
import os

# Read input
with open('/workspace/input.txt') as f:
    data = f.read()

# Process
result = data.upper()

# Write output
with open('/workspace/output.txt', 'w') as f:
    f.write(result)

print("Agent completed!")
"""

        result = run_with_bwrap(
            ["python3", "-c", agent_code],
            workspace_root=workspace,
            readonly=False,
            timeout=10,
        )

        assert result.returncode == 0
        assert "Agent completed!" in result.stdout
        assert (workspace / "output.txt").exists()
        assert (workspace / "output.txt").read_text() == "PROCESS THIS"


def test_timeout():
    """Test that timeout works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        with pytest.raises(subprocess.TimeoutExpired):
            run_with_bwrap(
                ["sleep", "60"],
                workspace_root=workspace,
                timeout=1,
            )


if __name__ == "__main__":
    import subprocess

    print("Testing bubblewrap isolation...")
    print(f"Bwrap available: {is_bwrap_available()}")

    if not is_bwrap_available():
        print("Bubblewrap not installed - skipping tests")
        sys.exit(0)

    # Run pytest
    sys.exit(pytest.main([__file__, "-v"]))
