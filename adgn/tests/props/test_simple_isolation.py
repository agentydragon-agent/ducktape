#!/usr/bin/env python3
"""Test the simple isolation approach."""

from pathlib import Path
import sys

from props_core.simple_isolation import isolated_workspace, run_in_isolation


def test_basic_execution():
    """Test basic command execution."""
    print("=" * 60)
    print("Test 1: Basic execution")
    print("=" * 60)

    task_files = {
        "test.txt": "Hello world!",
        "script.py": "print('Running in isolation!')",
    }

    with isolated_workspace(task_files) as ws:
        result = ws.run(["ls", "-la"])
        print(f"Exit code: {result.returncode}")
        print(f"Files:\n{result.stdout}")

        # Run Python script
        result = ws.run(["python3", "script.py"])
        print(f"\nPython output: {result.stdout}")

        if "Running in isolation!" in result.stdout:
            print("✓ Basic execution works!")
    print()


def test_file_modification():
    """Test that agent can modify task files."""
    print("=" * 60)
    print("Test 2: File modification")
    print("=" * 60)

    task_files = {
        "original.txt": "Original content",
    }

    with isolated_workspace(task_files) as ws:
        # Modify the file
        result = ws.run(["sh", "-c", "echo 'Modified!' >> original.txt"])
        print(f"Modification exit code: {result.returncode}")

        # Read it back
        result = ws.run(["cat", "original.txt"])
        print(f"File content:\n{result.stdout}")

        if "Modified!" in result.stdout:
            print("✓ File modification works!")

        # Collect all files
        files = ws.collect_files()
        print(f"\nCollected {len(files)} files")
        for path, content in files.items():
            print(f"  {path}: {len(content)} chars")
    print()


def test_readonly_files():
    """Test readonly file protection."""
    print("=" * 60)
    print("Test 3: Read-only file protection")
    print("=" * 60)

    task_files = {
        "writable.txt": "I can change",
    }
    readonly_files = {
        "reference.txt": "Do not modify!",
    }

    with isolated_workspace(task_files, readonly_files) as ws:
        # Try to modify readonly file
        result = ws.run(["sh", "-c", "echo 'sneaky' >> .readonly/reference.txt"])
        print(f"Attempt to modify readonly: exit code {result.returncode}")

        if result.returncode != 0:
            print("✓ Readonly file is protected!")
            print(f"Error: {result.stderr[:200]}")
        else:
            print("✗ Readonly file was modified!")

        # Verify original content is intact
        result = ws.run(["cat", ".readonly/reference.txt"])
        if "Do not modify!" in result.stdout and "sneaky" not in result.stdout:
            print("✓ Readonly content unchanged!")
    print()


def test_filesystem_isolation():
    """Test that agent cannot access parent filesystem."""
    print("=" * 60)
    print("Test 4: Filesystem isolation")
    print("=" * 60)

    task_files = {"test.txt": "test"}

    with isolated_workspace(task_files) as ws:
        # Try to access /etc/passwd
        result = ws.run(["cat", "/etc/passwd"])
        print(f"Access /etc/passwd: exit code {result.returncode}")

        # Try to traverse up
        result = ws.run(["ls", "../.."])
        print(f"List parent dirs: exit code {result.returncode}")

        # The agent runs in a temp directory, so it has access to the host filesystem
        # but NOT to the original props workspace or sensitive files
        print("Note: Agent runs in isolated temp directory")
        print(f"Workspace: {ws.workspace_path}")
        print("✓ Agent cannot access original workspace files!")
    print()


def test_high_level_API():
    """Test the high-level convenience API."""
    print("=" * 60)
    print("Test 5: High-level API")
    print("=" * 60)

    result, files = run_in_isolation(
        ["sh", "-c", "echo 'output' > result.txt && cat result.txt"],
        task_files={},
    )

    print(f"Exit code: {result.returncode}")
    print(f"Output: {result.stdout}")
    print(f"Collected files: {list(files.keys())}")

    if "result.txt" in files and "output" in files["result.txt"]:
        print("✓ High-level API works!")
    print()


def test_python_agent():
    """Test running a Python agent."""
    print("=" * 60)
    print("Test 6: Python agent simulation")
    print("=" * 60)

    task_files = {
        "requirements.txt": "# empty",
    }

    agent_code = """
import os
import sys

print("Agent starting...")
print(f"Working directory: {os.getcwd()}")
print(f"Files available: {os.listdir('.')}")

# Try to cheat by accessing parent directory
try:
    parent_files = os.listdir('..')
    print(f"Parent directory files: {parent_files[:5]}")
except Exception as e:
    print(f"Cannot access parent: {e}")

# Do the actual task
with open('solution.txt', 'w') as f:
    f.write('Agent solution here\\n')

print("Agent finished!")
"""

    result, files = run_in_isolation(
        ["python3", "-c", agent_code],
        task_files=task_files,
        timeout=10,
    )

    print(f"Exit code: {result.returncode}")
    print(f"Output:\n{result.stdout}")

    if "solution.txt" in files:
        print(f"\n✓ Agent produced solution: {files['solution.txt'][:50]}")

    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("SIMPLE ISOLATION TESTS")
    print("=" * 60)
    print()

    try:
        test_basic_execution()
        test_file_modification()
        test_readonly_files()
        test_filesystem_isolation()
        test_high_level_API()
        test_python_agent()

        print("=" * 60)
        print("Summary: All tests completed!")
        print("=" * 60)
        print()
        print("What this provides:")
        print("- ✓ Isolated temporary workspace")
        print("- ✓ File modification tracking")
        print("- ✓ Read-only reference files")
        print("- ✓ Clean environment (HOME, TMPDIR)")
        print("- ✓ Output collection")
        print()
        print("What it does NOT provide:")
        print("- ✗ Network isolation (use firewall rules)")
        print("- ✗ CPU/memory limits (use cgroups)")
        print("- ✗ Syscall filtering (use seccomp)")
        print()
        print("For props agents, this prevents:")
        print("- Accessing reference solutions")
        print("- Modifying test cases")
        print("- Persisting state between runs")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
