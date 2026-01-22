"""CLI entrypoint for registry proxy service."""

from __future__ import annotations

import os

import uvicorn

from props.registry_proxy.proxy import app


def main() -> None:
    """Main entry point."""
    port = int(os.environ.get("PORT", "5051"))
    log_level = os.environ.get("LOG_LEVEL", "info")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=log_level)


if __name__ == "__main__":
    main()
