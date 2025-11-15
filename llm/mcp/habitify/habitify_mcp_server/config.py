"""Configuration utilities for Habitify MCP server."""

import logging
import os
import sys

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def load_api_key(api_key_override: str | None = None, exit_on_missing: bool = True, logger_func=None) -> str | None:
    """
    Load the Habitify API key from various sources.

    Args:
        api_key_override: Optional API key to use instead of environment variable
        exit_on_missing: Whether to exit the program if API key is missing
        logger_func: Optional logging function to use for error messages
                    (defaults to logger.error for logging, or print if no logger)

    Returns:
        The API key if found, None if not found and exit_on_missing is False

    Raises:
        SystemExit: If exit_on_missing is True and no API key is found
    """
    # Load environment variables from .env file
    load_dotenv()

    # Set API key from override if provided
    if api_key_override:
        os.environ["HABITIFY_API_KEY"] = api_key_override

    # Get API key from environment
    api_key = os.environ.get("HABITIFY_API_KEY")

    if not api_key:
        # Determine which function to use for error messages
        if logger_func is None:
            logger_func = logger.error if logger.handlers else print

        # Show error messages
        logger_func("Error: HABITIFY_API_KEY environment variable is required")
        logger_func("Please set it using one of these methods:")
        logger_func("  1. Add it to your .env file: HABITIFY_API_KEY=your_api_key_here")
        logger_func("  2. Set it as an environment variable: export HABITIFY_API_KEY=your_api_key_here")

        # Add command-line option hint if appropriate
        if api_key_override is not None:  # Means the caller supports --api-key
            logger_func("  3. Pass it as a command-line argument: --api-key=your_api_key_here")

        if exit_on_missing:
            sys.exit(1)

    return api_key


def get_api_base_url() -> str | None:
    """Get the optional Habitify API base URL from environment."""
    return os.environ.get("HABITIFY_API_BASE_URL")
