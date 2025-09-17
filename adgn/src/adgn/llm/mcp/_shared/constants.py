# Shared constants for MCP mcp/_shared modules

# Shared startup command for long-lived containers
SLEEP_FOREVER_CMD: list[str] = ["/bin/sh", "-lc", "sleep infinity"]
