"""
Example script to test the Habitify MCP server using mcp dev.

This script sets up a mock server file that can be run with the MCP dev command
to view and interact with the tools in a debug environment.

The MCP dev environment provides a convenient way to test MCP servers without
requiring a full Claude Desktop installation.
"""

import argparse
import logging
from pathlib import Path
import subprocess
import sys
import tempfile

# Add the parent directory to the path so we can import the server
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from habitify_mcp_server.config import load_api_key

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("habitify-mcp-dev")


# Parse command line arguments
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run the Habitify MCP server in dev mode")
    parser.add_argument("--api-key", help="Habitify API key (overrides HABITIFY_API_KEY environment variable)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--debug-tools", action="store_true", help="Enable MCP debugging for tools")
    return parser.parse_args()


# Template for the server file
SERVER_TEMPLATE = """
import os
import logging
from habitify_mcp_server.server import create_habitify_mcp_server

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("habitify-mcp-dev-server")

# Set up the server
server = create_habitify_mcp_server()

# Print available tools for reference
logger.info("Habitify MCP Server ready with these tools:")

# Server is ready!
logger.info("Use 'run_tool <tool_name> [args]' to test tools")
"""


def main() -> int:
    """Main entry point for the script."""
    # Parse command-line arguments
    args = parse_args()

    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Load API key using our common utility
    api_key = load_api_key(api_key_override=args.api_key, exit_on_missing=False, logger_func=logger.error)
    if not api_key:
        return 1

    # Create a temporary file with the server code
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as temp:
        temp_filename = temp.name
        temp.write(SERVER_TEMPLATE)

    logger.info(f"Created temporary server file: {temp_filename}")

    try:
        # Build the command
        cmd = ["mcp", "dev", temp_filename, "--with-editable", "."]

        if args.debug_tools:
            cmd.append("--debug")

        # Run the MCP dev command
        logger.info("Starting MCP dev environment...")
        logger.info("You can test tools using the 'run_tool' command in the dev environment")
        logger.info("Example: run_tool get_habits")
        logger.info("Press Ctrl+C to exit")

        subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running MCP dev: {e}")
        return 1
    except FileNotFoundError:
        logger.error("Error: 'mcp' command not found. Make sure the MCP SDK is installed.")
        logger.error('You can install it with: pip install "mcp[cli]"')
        return 1
    except KeyboardInterrupt:
        logger.info("\nMCP dev environment stopped.")
        return 0
    finally:
        # Clean up the temporary file
        try:
            Path(temp_filename).unlink()
            logger.info(f"Removed temporary server file: {temp_filename}")
        except Exception as e:
            logger.warning(f"Failed to remove temporary file: {e}")


if __name__ == "__main__":
    sys.exit(main())
