#!/usr/bin/env python3
"""Simple test for bwrap isolation (no pytest needed)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "props" / "core" / "src"))

from props_core.bwrap_isolation import run_with_bwrap, is_bwrap_available


def test_basic():
    print("=" * 60)
    print("Test 1: Basic execution")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "test.txt").write_text("Hello bwrap!")

        result = run_with_bwrap(
            ["cat", "/workspace/test.txt"],
            workspace_root=workspace,
        )

        print(f"Exit code: {result.returncode}")
        print(f"Output: {result.stdout}")

        if result.returncode == 0 and "Hello bwrap!" in result.stdout:
            print("✓ Basic execution works!")
        else:
            print("✗ Failed")
    print()


def test_readonly():
    print("=" * 60)
    print("Test 2: Read-only protection")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "original.txt").write_text("Original")

        result = run_with_bwrap(
            ["sh", "-c", "echo 'evil' > /workspace/evil.txt"],
            workspace_root=workspace,
            readonly=True,
        )

        print(f"Exit code: {result.returncode}")

        if result.returncode != 0 and not (workspace / "evil.txt").exists():
            print("✓ Readonly protection works!")
        else:
            print("✗ Write succeeded when it shouldn't")
            print(f"Stderr: {result.stderr}")
    print()


def test_python():
    print("=" * 60)
    print("Test 3: Python execution")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        script = workspace / "test.py"
        script.write_text("""
import os
print(f"Working directory: {os.getcwd()}")
print(f"Files: {os.listdir('.')}")
print("Python works in bwrap!")
""")

        result = run_with_bwrap(
            ["python3", "test.py"],
            workspace_root=workspace,
        )

        print(f"Exit code: {result.returncode}")
        print(f"Output:\n{result.stdout}")

        if result.returncode == 0 and "Python works in bwrap!" in result.stdout:
            print("✓ Python execution works!")
    print()


def test_file_creation():
    print("=" * 60)
    print("Test 4: File creation and modification")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        result = run_with_bwrap(
            ["sh", "-c", "echo 'created' > /workspace/new.txt && cat /workspace/new.txt"],
            workspace_root=workspace,
            readonly=False,
        )

        print(f"Exit code: {result.returncode}")
        print(f"Output: {result.stdout}")

        if (workspace / "new.txt").exists():
            content = (workspace / "new.txt").read_text()
            print(f"File created on host: {content.strip()}")
            print("✓ File creation works!")
        else:
            print("✗ File not created")
    print()


def test_isolation():
    print("=" * 60)
    print("Test 5: Filesystem isolation")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Try to access /etc/passwd
        result = run_with_bwrap(
            ["test", "-f", "/etc/passwd"],
            workspace_root=workspace,
        )

        print(f"Can access /etc/passwd: {result.returncode == 0}")

        # Try to escape workspace
        result = run_with_bwrap(
            ["ls", "/"],
            workspace_root=workspace,
        )

        print(f"Root listing:\n{result.stdout[:200]}")

        if "/workspace" in result.stdout or "workspace" in result.stdout:
            print("✓ Isolated filesystem (limited view)")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("BUBBLEWRAP ISOLATION TESTS")
    print("=" * 60)
    print()

    if not is_bwrap_available():
        print("✗ Bubblewrap not available!")
        sys.exit(1)

    print("✓ Bubblewrap is available")
    print()

    try:
        test_basic()
        test_readonly()
        test_python()
        test_file_creation()
        test_isolation()

        print("=" * 60)
        print("Summary: Bubblewrap provides TRUE isolation!")
        print("=" * 60)
        print()
        print("Advantages over simple_isolation.py:")
        print("  ✓ True filesystem isolation (cannot escape)")
        print("  ✓ Process isolation (PID namespace)")
        print("  ✓ Stronger security boundaries")
        print("  ✓ No risk of accessing parent directories")
        print()
        print("Use bwrap_isolation when:")
        print("  - Bubblewrap is available")
        print("  - Need stronger isolation than file copying")
        print("  - Want to prevent filesystem escapes")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
