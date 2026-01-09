"""Shared logging callback for Typer CLI applications.

Provides a standard callback decorator that configures logging via --log-output and --log-level flags.
"""

from typing import Annotated

import typer

from cli_util.logging_config import VALID_LOG_LEVELS, configure_logging


def make_logging_callback(default_level: str = "INFO"):
    """Create a Typer callback for logging configuration.

    Args:
        default_level: Default log level if not specified

    Returns:
        A callback function suitable for use with @app.callback()

    Usage:
        app = typer.Typer()
        app.callback()(make_logging_callback(default_level="INFO"))
    """

    def _callback(
        log_output: Annotated[
            str,
            typer.Option(
                "--log-output",
                envvar="ADGN_LOG_OUTPUT",
                help="Where to send logs: 'stderr' (default), 'stdout', 'none', or a file path",
            ),
        ] = "stderr",
        log_level: Annotated[
            str,
            typer.Option(
                "--log-level",
                envvar="ADGN_LOG_LEVEL",
                help=f"Log level: {', '.join(VALID_LOG_LEVELS)} (default: {default_level})",
            ),
        ] = default_level,
    ) -> None:
        """Configure logging for all subcommands."""
        configure_logging(log_output=log_output, log_level=log_level)

    return _callback
