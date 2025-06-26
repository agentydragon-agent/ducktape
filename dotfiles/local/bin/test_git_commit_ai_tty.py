#!/usr/bin/env python3
"""Test the TTY output rendering for git_commit_ai.py"""

import asyncio
import os
import pty
import select
import sys
import time

# Simulate pre-commit output patterns
PRECOMMIT_OUTPUTS = [
    # Simple passing hooks
    """Trim Trailing Whitespace................................................Passed
Fix End of Files.........................................................Passed
Check Yaml...............................................................Passed
""",
    # Hooks with spinners and progress
    """black....................................................................Passed
isort....................................................................Passed
mypy.....................................................................Failed
- hook id: mypy
- exit code: 1

main.py:42: error: Incompatible types in assignment
main.py:55: error: Missing return statement
""",
    # Long running hook with updates
    """pytest...................................................................Running
  test_foo.py::test_something PASSED                              [ 20%]
  test_foo.py::test_another PASSED                                [ 40%]
  test_bar.py::test_complex FAILED                                [ 60%]
  test_bar.py::test_simple PASSED                                 [ 80%]
  test_baz.py::test_final PASSED                                  [100%]
pytest...................................................................Failed
""",
]


async def simulate_precommit_output(fd, output_script):
    """Simulate pre-commit writing output to a PTY."""
    for line in output_script.split("\n"):
        if not line:
            continue
        # Simulate progressive output
        os.write(fd, line.encode() + b"\n")
        await asyncio.sleep(0.1)  # Simulate work being done


async def simulate_claude_api(delay=2.0, should_fail=False):
    """Simulate Claude API call."""
    await asyncio.sleep(delay)
    if should_fail:
        raise Exception("Claude API error")
    return "feat: add new feature"


async def test_status_line_rendering():
    """Test that status line stays at bottom during pre-commit output."""

    # Create a pseudo-terminal
    master_fd, slave_fd = pty.openpty()

    # Mock the git_commit_ai components
    class FakeTaskState:
        def __init__(self, task):
            self.task = task
            self.start_time = time.time()

        @property
        def elapsed(self):
            return time.time() - self.start_time

        @property
        def status(self):
            if not self.task.done():
                return "running"
            try:
                self.task.result()
                return "success"
            except Exception:
                return "failed"

    # Create tasks
    ai_task = asyncio.create_task(simulate_claude_api(3.0))
    precommit_task = asyncio.create_task(
        simulate_precommit_output(slave_fd, PRECOMMIT_OUTPUTS[1]),
    )

    # Simulate the status update loop
    async def update_status():
        while not (ai_task.done() and precommit_task.done()):
            # This is where the status line would be rendered
            status = "\r⠋ AI: running, Pre-commit: running  "
            sys.stdout.write(status)
            sys.stdout.flush()
            await asyncio.sleep(0.1)

    # Simulate reading from PTY
    async def read_pty_output():
        while not precommit_task.done():
            readable, _, _ = select.select([master_fd], [], [], 0.01)
            if readable:
                try:
                    data = os.read(master_fd, 1024)
                    if data:
                        # Clear status line before writing pre-commit output
                        sys.stdout.write("\r" + " " * 80 + "\r")
                        sys.stdout.write(data.decode())
                        sys.stdout.flush()
                except OSError:
                    break
            await asyncio.sleep(0.01)

    # Run all tasks
    await asyncio.gather(
        ai_task,
        precommit_task,
        update_status(),
        read_pty_output(),
        return_exceptions=True,
    )

    os.close(master_fd)
    os.close(slave_fd)


def test_rich_alternative():
    """Test using Rich library for proper status line handling."""
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    console = Console()

    def generate_status_table(ai_status, precommit_status, elapsed):
        table = Table(show_header=False, box=None)
        table.add_row(
            f"⏳ AI: {ai_status}",
            f"Pre-commit: {precommit_status}",
            f"Elapsed: {elapsed:.1f}s",
        )
        return table

    # Rich handles the terminal properly with Live display
    with Live(
        generate_status_table("running", "running", 0.0),
        console=console,
    ) as live:
        for i in range(50):
            time.sleep(0.1)
            live.update(generate_status_table("running", "running", i * 0.1))
            # Pre-commit output would be printed above the live display
            if i % 10 == 0:
                console.print(f"Some pre-commit output line {i}")


if __name__ == "__main__":
    print("Testing TTY output rendering...")
    print("=" * 80)

    print("\n1. Testing current approach (status line mixed with output):")
    asyncio.run(test_status_line_rendering())

    print("\n\n2. Testing Rich library approach (proper status line):")
    test_rich_alternative()
