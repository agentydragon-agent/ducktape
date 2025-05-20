"""
Script to install the Habitify MCP server to Claude Desktop.

This script helps you install the Habitify MCP server to Claude Desktop,
making its tools available to Claude for habit tracking.
"""

import os
import subprocess
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check if API key is set
api_key = os.environ.get("HABITIFY_API_KEY")
if not api_key:
    print("Error: HABITIFY_API_KEY environment variable is required")
    print("Please set it using one of these methods:")
    print("  1. Add it to your .env file: HABITIFY_API_KEY=your_api_key_here")
    print("  2. Set it as an environment variable: export HABITIFY_API_KEY=your_api_key_here")
    sys.exit(1)

# Prepare the installation command
# Note: We need to use the module name, not the path
mcp_module = "habitify_mcp_server.server:create_habitify_mcp_server"
server_name = "Habitify"
env_vars = [f"HABITIFY_API_KEY={api_key}"]

# Optional API base URL if set
api_base_url = os.environ.get("HABITIFY_API_BASE_URL")
if api_base_url:
    env_vars.append(f"HABITIFY_API_BASE_URL={api_base_url}")

# Build the command
cmd = ["mcp", "install", mcp_module, "--name", server_name]
for env_var in env_vars:
    cmd.extend(["-v", env_var])

print("Installing Habitify MCP server to Claude Desktop...")
print(f"Server module: {mcp_module}")
print(f"Server name: {server_name}")

# Run the MCP install command
try:
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout)
except subprocess.CalledProcessError as e:
    print(f"Error installing MCP server: {e}")
    if e.stderr:
        print(e.stderr)
    sys.exit(1)
except FileNotFoundError:
    print("Error: 'mcp' command not found. Make sure the MCP SDK is installed.")
    print('You can install it with: pip install "mcp[cli]"')
    sys.exit(1)

print("\nHabitify MCP server successfully installed to Claude Desktop!")
