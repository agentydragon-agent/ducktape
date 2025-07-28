"""Shell utilities for command emission and error handling."""

import sys


def emit_command(cmd: str) -> None:
    """Emit a command for shell execution via fd3."""
    try:
        import os

        os.write(3, (cmd + "\n").encode())
    except OSError:
        # fd3 not available (e.g., in tests or non-shell environments)
        # Silently ignore - this is expected in many contexts
        pass


def controlled_error(message: str, commands: list[str] | None = None) -> None:
    """Exit with a controlled error message and optional commands."""
    import click

    click.echo(f"Error: {message}")
    if commands:
        for cmd in commands:
            emit_command(cmd)
    sys.exit(2)  # Controlled error - eval fd 3 contents
