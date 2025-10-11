from __future__ import annotations

import anyio

from adgn.mcp.echo.server import make_echo_server


def main() -> None:
    # Build a simple echo server and run over stdio using FastMCP's runner
    server = make_echo_server("echo")
    anyio.run(server.run_stdio_async)


if __name__ == "__main__":
    main()
