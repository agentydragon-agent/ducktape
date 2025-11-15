"""
Example script to run the Habitify MCP server.

This script creates and starts the Habitify MCP server with either stdio transport
(for Claude Desktop) or SSE transport (for HTTP-based web integrations).
"""

import argparse
import logging
from pathlib import Path
import sys

# Add the parent directory to the path so we can import the server
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from habitify_mcp_server import create_habitify_mcp_server
from habitify_mcp_server.config import load_api_key

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("habitify-mcp-example")


# Parse command line arguments
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run the Habitify MCP server")
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio", help="Transport type (stdio or sse, default: stdio)"
    )
    parser.add_argument("--port", type=int, default=3000, help="Port to use for SSE transport (default: 3000)")
    parser.add_argument("--api-key", help="Habitify API key (overrides HABITIFY_API_KEY environment variable)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


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

    # Import here so we only import after checking API key

    try:
        # Create the server (with port configuration)
        logger.info("Creating Habitify MCP server...")
        server = create_habitify_mcp_server(port=args.port)

        # Run the server with the specified transport
        if args.transport == "stdio":
            logger.info("Starting server with stdio transport...")
            server.run(transport="stdio")
        else:
            logger.info(f"Starting server with SSE transport on port {args.port}...")
            server.run(transport="sse")  # Port is already configured in the server

        return 0
    except KeyboardInterrupt:
        logger.info("Server stopped by keyboard interrupt")
        return 0
    except Exception as e:
        logger.error(f"Error running server: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
