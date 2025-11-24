#!/usr/bin/env python3
"""Demo script to test the unshare-based isolation."""

from pathlib import Path
import tempfile
import sys

# Note: unshare_isolation was an experimental approach not included in final implementation
# from props_core.unshare_isolation import run_isolated


def test_basic_isolation():
    """Test basic command execution in isolated environment."""
    print("=" * 60)
    print("Test 1: Basic isolation - running echo in isolated env")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir()
        (workspace / "test.txt").write_text("Hello from workspace!")

        result = run_isolated(
            ["ls", "-la", "/workspace"],
            workspace_root=workspace,
            capture_output=True,
        )

        print(f"Exit code: {result.returncode}")
        print(f"Output:\n{result.stdout}")
        if result.returncode == 0:
            print("✓ Basic isolation works!")
        else:
            print(f"✗ Failed: {result.stderr}")
    print()


def test_readonly_protection():
    """Test that readonly workspace prevents writes."""
    print("=" * 60)
    print("Test 2: Read-only protection")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir()
        (workspace / "original.txt").write_text("Original content")

        # Try to write - should fail with readonly
        result = run_isolated(
            ["sh", "-c", "echo 'sneaky' > /workspace/evil.txt"],
            workspace_root=workspace,
            readonly=True,
            capture_output=True,
        )

        print(f"Exit code: {result.returncode}")
        if result.returncode != 0:
            print("✓ Write correctly blocked in readonly mode!")
            print(f"Error: {result.stderr[:200]}")
        else:
            print("✗ WARNING: Write succeeded when it should have failed!")

        # Verify file wasn't created on host
        evil_file = workspace / "evil.txt"
        if not evil_file.exists():
            print("✓ File NOT created on host filesystem!")
        else:
            print("✗ WARNING: File was created on host!")
    print()


def test_filesystem_boundary():
    """Test that agent cannot access files outside workspace."""
    print("=" * 60)
    print("Test 3: Filesystem boundary protection")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir()

        # Try to access parent directory
        result = run_isolated(
            ["ls", "-la", "/"],
            workspace_root=workspace,
            capture_output=True,
        )

        print(f"Exit code: {result.returncode}")
        print(f"Root directory contents:\n{result.stdout[:500]}")

        # Should only see our mounted directories
        if "/workspace" in result.stdout and "bin" not in result.stdout:
            print("✓ Filesystem isolation working - limited view of /")
        else:
            print("✗ Can see host filesystem")
    print()


def test_python_execution():
    """Test running Python code in isolated environment."""
    print("=" * 60)
    print("Test 4: Python code execution")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir()

        # Create a Python script
        script = workspace / "test.py"
        script.write_text("""
import os
import sys

print(f"Python version: {sys.version}")
print(f"Current directory: {os.getcwd()}")
print(f"Directory contents: {os.listdir('.')}")
print(f"Can we write? Let's try...")

try:
    with open('output.txt', 'w') as f:
        f.write('test')
    print("✗ Write succeeded (should have failed in readonly mode)")
except Exception as e:
    print(f"✓ Write blocked: {e}")
""")

        result = run_isolated(
            ["python3", "/workspace/test.py"],
            workspace_root=workspace,
            readonly=True,
            capture_output=True,
        )

        print(f"Exit code: {result.returncode}")
        print(f"Output:\n{result.stdout}")
        if result.stderr:
            print(f"Errors:\n{result.stderr}")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("ISOLATION TESTS FOR PROPS AGENTS")
    print("=" * 60)
    print()

    try:
        test_basic_isolation()
        test_readonly_protection()
        test_filesystem_boundary()
        test_python_execution()

        print("=" * 60)
        print("All tests completed!")
        print("=" * 60)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
